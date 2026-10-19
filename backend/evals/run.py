"""Evaluation runner.

Tool mode (no LLM, runs in CI): each case's reference operation is executed through the real
ingestion pipeline and sandboxed engine, and every ground-truth figure must appear in the
result. This measures the correctness of the analytical layer.

Agent mode (real LLM, costs money): the full workflow answers each question; the report scores
task success, numeric accuracy of the answer, whether the computed results hold the truth, tool
choice, column identification, entity mentions, grounding, chart/data consistency,
unanswerable and ambiguous handling, follow-up context and limit enforcement.

    uv run python -m evals.run --mode tools
    ANTHROPIC_API_KEY=... uv run python -m evals.run --mode agent [--case ID ...]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from app.agent.context import DatasetContext, PriorTurn
from app.agent.graph import AgentDeps, AgentLimits, AnalysisAgent
from app.agent.llm.base import LLMProvider
from app.agent.schemas import AgentOutcome, StoredResult
from app.agent.tools import ToolExecutor
from app.analytics.engine import AnalyticsEngine, EngineLimits
from app.analytics.operations import AnalysisOperation
from app.datasets.inference import infer_table
from app.datasets.ingest import IngestLimits, read_csv
from app.datasets.profiling import build_profile
from evals import datasets
from evals.cases import CASES, CASES_BY_ID, Case
from evals.scoring import (
    aliases,
    answer_text,
    charts_consistent,
    columns_used,
    operations_used,
    result_contains,
    result_mentions,
    text_mentions,
    text_states,
)

RESULTS_DIR = Path(__file__).resolve().parent / "results"


@dataclass
class LoadedDataset:
    parquet: Path
    columns: list[dict[str, Any]]
    profile: dict[str, Any]

    def context(self, name: str) -> DatasetContext:
        return DatasetContext.from_dataset(name=name, columns=self.columns, profile=self.profile)


def load_dataset(name: str, directory: Path) -> LoadedDataset:
    """The same path an upload takes: parse, infer types, profile, write Parquet."""
    raw = read_csv(datasets.csv_bytes(name), IngestLimits(1_000_000, 200, 50_000_000, 1))
    typed = infer_table(raw.headers, raw.frame)
    profile = build_profile(typed.frame, typed.columns, typed.notes)
    path = directory / f"{name}.parquet"
    typed.frame.to_parquet(path, index=False)
    return LoadedDataset(path, [asdict(c) for c in typed.columns], profile.model_dump(mode="json"))


# --- Tool mode -------------------------------------------------------------------------------


@dataclass
class ToolCaseReport:
    id: str
    passed: bool
    checks: list[str] = field(default_factory=list)


def run_tools(cases: list[Case]) -> list[ToolCaseReport]:
    reports = []
    adapter = TypeAdapter(AnalysisOperation)
    frames = datasets.frames()
    with tempfile.TemporaryDirectory() as tmp:
        loaded = {name: load_dataset(name, Path(tmp)) for name in {c.dataset for c in cases}}
        for case in cases:
            if case.reference is None:
                continue
            data = loaded[case.dataset]
            frame = frames[case.dataset]
            report = ToolCaseReport(case.id, True)
            with AnalyticsEngine(data.parquet, EngineLimits()) as engine:
                outcome = adapter.validate_python(case.reference).run(
                    engine, data.context(case.dataset).schema()
                )
            stored = [
                StoredResult(
                    id="r1",
                    tool="execute_analysis",
                    operation=outcome.operation,
                    description=outcome.description,
                    table=outcome.table,
                    summary=outcome.summary,
                )
            ]
            for truth in case.truths:
                value = float(truth.compute(frame))
                ok = result_contains(stored, value, tolerance=truth.relative_tolerance)
                report.checks.append(f"{'PASS' if ok else 'FAIL'} {truth.label}: {value:,.6g}")
                report.passed &= ok
            for entity_fn in case.entities:
                entity = entity_fn(frame)
                ok = result_mentions(stored, entity)
                report.checks.append(
                    f"{'PASS' if ok else 'FAIL'} mentions {' / '.join(aliases(entity))}"
                )
                report.passed &= ok
            reports.append(report)
    return reports


# --- Agent mode ------------------------------------------------------------------------------


@dataclass
class AgentCaseReport:
    id: str
    category: str
    question: str
    status: str
    stop_reason: str
    seconds: float
    input_tokens: int
    output_tokens: int
    tool_calls: int
    scores: dict[str, float | None]
    notes: list[str] = field(default_factory=list)
    summary: str | None = None


def _score(
    case: Case, outcome: AgentOutcome, frame: Any, known: set[str]
) -> tuple[dict[str, float | None], list[str]]:
    scores: dict[str, float | None] = {}
    notes: list[str] = []
    text = answer_text(outcome)
    scores["completed"] = 1.0 if outcome.status == "completed" and outcome.answer else 0.0

    if not case.answerable:
        declined = (outcome.plan is not None and not outcome.plan.answerable) or (
            outcome.stop_reason == "not_answerable"
        )
        scores["unanswerable_handled"] = 1.0 if declined else 0.0
        if not declined:
            notes.append("Answered a question the data cannot answer.")
        return scores, notes

    if case.truths:
        stated = computed = 0
        for truth in case.truths:
            value = float(truth.compute(frame))
            in_text = text_states(
                text, value, percent=truth.percent, tolerance=truth.relative_tolerance
            )
            in_results = result_contains(outcome.results, value, tolerance=truth.relative_tolerance)
            stated += in_text
            computed += in_results
            if not in_text:
                notes.append(f"Answer does not state {truth.label} ({value:,.6g}).")
            if not in_results:
                notes.append(f"No computed result holds {truth.label} ({value:,.6g}).")
        scores["numeric_accuracy"] = stated / len(case.truths)
        scores["computed_correctly"] = computed / len(case.truths)
    if case.entities:
        hits = 0
        for entity_fn in case.entities:
            entity = entity_fn(frame)
            found = text_mentions(text, entity)
            hits += found
            if not found:
                notes.append(f"Answer does not mention {' / '.join(aliases(entity))}.")
        scores["entity_accuracy"] = hits / len(case.entities)
    if case.expected_operations:
        used = operations_used(outcome)
        scores["tool_selection"] = 1.0 if used & set(case.expected_operations) else 0.0
        if not scores["tool_selection"]:
            notes.append(f"Operations used: {sorted(used) or 'none'}.")
    if case.expected_columns:
        used_columns = columns_used(outcome, known)
        expected = set(case.expected_columns)
        scores["column_identification"] = len(expected & used_columns) / len(expected)
    if case.expect_interpretation:
        scores["interpretation_stated"] = (
            1.0 if outcome.plan is not None and outcome.plan.interpretation else 0.0
        )
    scores["grounded"] = 1.0 if outcome.grounding is not None and outcome.grounding.passed else 0.0
    scores["charts_consistent"] = 1.0 if charts_consistent(outcome) else 0.0
    if case.limits:
        within = outcome.tool_calls <= case.limits.get("max_tool_calls", 10**6)
        scores["limits_respected"] = 1.0 if within and outcome.status == "completed" else 0.0
    return scores, notes


def run_agent(
    cases: list[Case], provider_factory: Callable[[], LLMProvider]
) -> list[AgentCaseReport]:
    reports: list[AgentCaseReport] = []
    outcomes: dict[str, AgentOutcome] = {}
    frames = datasets.frames()
    with tempfile.TemporaryDirectory() as tmp:
        loaded = {name: load_dataset(name, Path(tmp)) for name in {c.dataset for c in cases}}
        for case in cases:
            data = loaded[case.dataset]
            context = data.context(case.dataset)
            history: list[PriorTurn] = []
            chain = case.follow_up_of
            ancestry: list[Case] = []
            while chain:
                ancestry.insert(0, CASES_BY_ID[chain])
                chain = CASES_BY_ID[chain].follow_up_of
            for earlier in ancestry:
                previous = outcomes.get(earlier.id)
                history.append(
                    PriorTurn.from_outcome(
                        earlier.question,
                        previous.status if previous else "failed",
                        previous.model_dump(mode="json") if previous else None,
                    )
                )
            provider = provider_factory()
            started = time.monotonic()
            with AnalyticsEngine(data.parquet, EngineLimits()) as engine:
                agent = AnalysisAgent(
                    AgentDeps(
                        provider=provider,
                        executor=ToolExecutor(engine=engine, context=context, profile=data.profile),
                        context=context,
                        history=history,
                        limits=AgentLimits(**case.limits) if case.limits else AgentLimits(),
                    )
                )
                outcome = agent.run(case.question)
            elapsed = time.monotonic() - started
            outcomes[case.id] = outcome
            known = {c.name for c in context.columns}
            scores, notes = _score(case, outcome, frames[case.dataset], known)
            reports.append(
                AgentCaseReport(
                    id=case.id,
                    category=case.category,
                    question=case.question,
                    status=outcome.status,
                    stop_reason=outcome.stop_reason,
                    seconds=round(elapsed, 2),
                    input_tokens=int(outcome.usage.get("input_tokens", 0)),
                    output_tokens=int(outcome.usage.get("output_tokens", 0)),
                    tool_calls=outcome.tool_calls,
                    scores=scores,
                    notes=notes + ([outcome.error_message] if outcome.error_message else []),
                    summary=outcome.answer.summary if outcome.answer else None,
                )
            )
            print(f"[{case.id}] {outcome.status} {scores}", file=sys.stderr)
    return reports


def aggregate(reports: list[AgentCaseReport]) -> dict[str, float]:
    metrics: dict[str, list[float]] = {}  # metric -> per-case values
    for report in reports:
        for key, value in report.scores.items():
            if value is not None:
                metrics.setdefault(key, []).append(value)
    summary = {key: round(statistics.mean(values), 3) for key, values in sorted(metrics.items())}
    summary["cases"] = len(reports)
    summary["mean_seconds"] = (
        round(statistics.mean(r.seconds for r in reports), 2) if reports else 0
    )
    summary["total_input_tokens"] = sum(r.input_tokens for r in reports)
    summary["total_output_tokens"] = sum(r.output_tokens for r in reports)
    return summary


def write_report(model: str, reports: list[AgentCaseReport], output: Path | None) -> Path:
    RESULTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = output or RESULTS_DIR / f"{stamp}-{model}.json"
    metrics = aggregate(reports)
    payload = {
        "model": model,
        "created_at": stamp,
        "aggregate": metrics,
        "cases": [asdict(r) for r in reports],
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")
    markdown = [f"# Agent evaluation: {model} ({stamp})", "", "| Metric | Value |", "|---|---|"]
    markdown += [f"| {k} | {v} |" for k, v in metrics.items()]
    markdown += ["", "| Case | Status | Scores | Notes |", "|---|---|---|---|"]
    for r in reports:
        scores = ", ".join(f"{k}={v:g}" for k, v in r.scores.items() if v is not None)
        markdown.append(f"| {r.id} | {r.status} | {scores} | {' '.join(r.notes)[:300]} |")
    path.with_suffix(".md").write_text("\n".join(markdown) + "\n", encoding="utf-8", newline="\n")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--mode", choices=["tools", "agent"], required=True)
    parser.add_argument("--case", action="append", help="Run only these case ids.")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    cases = [CASES_BY_ID[c] for c in args.case] if args.case else CASES

    if args.mode == "tools":
        tool_reports = run_tools(cases)
        for tool_report in tool_reports:
            print(f"{'PASS' if tool_report.passed else 'FAIL'} {tool_report.id}")
            for check in tool_report.checks:
                print(f"    {check}")
        failed = [r.id for r in tool_reports if not r.passed]
        print(f"\n{len(tool_reports) - len(failed)}/{len(tool_reports)} cases passed")
        raise SystemExit(1 if failed else 0)

    from app.agent.llm.anthropic_provider import AnthropicProvider
    from app.config import get_settings

    settings = get_settings()
    # Follow-up cases need their predecessors in the same run.
    wanted = {c.id for c in cases}
    for case in list(cases):
        chain = case.follow_up_of
        while chain and chain not in wanted:
            wanted.add(chain)
            chain = CASES_BY_ID[chain].follow_up_of
    ordered = [c for c in CASES if c.id in wanted]
    reports = run_agent(ordered, lambda: AnthropicProvider.from_settings(settings))
    path = write_report(settings.llm_model, reports, args.output)
    print(json.dumps(aggregate(reports), indent=2))
    print(f"Report: {path}")


if __name__ == "__main__":
    main()
