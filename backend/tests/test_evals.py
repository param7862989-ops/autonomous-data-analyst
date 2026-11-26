"""The evaluation harness: tool-mode evals must pass, and agent-mode scoring must tell a correct
answer from a wrong one. (Agent evals against a real model are run separately; see
docs/EVALUATION.md.)"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.agent.llm.base import AssistantTurn, ToolResults
from app.agent.llm.fake import Call, FakeProvider, done_turn, tool_turn
from app.agent.schemas import AnalysisPlan, StoredResult
from app.analytics.engine import TableResult
from evals.cases import CASES, CASES_BY_ID
from evals.run import aggregate, run_agent, run_tools, write_report
from evals.scoring import result_contains, text_states
from tests.scripted import COMPARISON, sales_provider
from tests.scripted import _plan as scripted_plan


def test_tool_mode_evals_pass() -> None:
    reports = run_tools(CASES)
    assert len(reports) >= 14
    failures = {r.id: r.checks for r in reports if not r.passed}
    assert failures == {}


def test_agent_scoring_rewards_a_correct_grounded_answer() -> None:
    reports = run_agent([CASES_BY_ID["sales-q3-decline"]], sales_provider)
    scores = reports[0].scores
    assert scores["completed"] == 1.0
    assert scores["numeric_accuracy"] == 1.0
    assert scores["computed_correctly"] == 1.0
    assert scores["entity_accuracy"] == 0.5  # the script never looks at products
    assert scores["tool_selection"] == 1.0
    assert scores["grounded"] == 1.0
    assert scores["charts_consistent"] == 1.0
    assert scores["interpretation_stated"] == 1.0
    assert reports[0].notes == ["Answer does not mention Standing Desk."]


def test_agent_scoring_catches_wrong_numbers_and_entities() -> None:
    def wrong() -> FakeProvider:
        provider = sales_provider()
        original = provider._structured

        def structured(call):  # type: ignore[no-untyped-def]
            reply = original(call)  # type: ignore[misc]
            if isinstance(reply, dict) and "summary" in reply:
                reply = {
                    **reply,
                    "summary": "Revenue fell 12% from $700,000, mostly in the North.",
                    "findings": [],
                }
            return reply

        provider._structured = structured  # type: ignore[assignment]
        return provider

    report = run_agent([CASES_BY_ID["sales-q3-decline"]], wrong)[0]
    assert report.scores["numeric_accuracy"] == 0.0
    assert report.scores["entity_accuracy"] == 0.0
    assert report.scores["grounded"] == 0.0  # $700,000 and 12% match no computed result
    assert report.scores["computed_correctly"] == 1.0  # the tools themselves were right
    assert any("does not state" in note for note in report.notes)


def test_unanswerable_case_scores_declining() -> None:
    def declining() -> FakeProvider:
        def structured(call):  # type: ignore[no-untyped-def]
            if call.schema.__name__ == "AnalysisPlan":
                return {
                    "intent": "other",
                    "answerable": False,
                    "missing_information": "There is no cost or profit column.",
                    "relevant_columns": [],
                    "interpretation": None,
                    "steps": [],
                }
            return {
                "summary": "This dataset has no cost data, so profit margin cannot be computed.",
                "findings": [],
                "caveats": [],
                "chart_ids": [],
                "follow_up_questions": [],
            }

        return FakeProvider(structured=structured)

    report = run_agent([CASES_BY_ID["sales-profit-margin-unanswerable"]], declining)[0]
    assert report.scores == {"completed": 1.0, "unanswerable_handled": 1.0}


def test_aggregate_metrics() -> None:
    reports = run_agent([CASES_BY_ID["sales-q3-decline"]], sales_provider)
    summary = aggregate(reports)
    assert summary["cases"] == 1
    assert summary["numeric_accuracy"] == pytest.approx(1.0)


def test_recovery_case_scores_retrying_after_a_failed_query() -> None:
    def retrying() -> FakeProvider:
        provider = sales_provider()

        def tool_step(call: Call) -> AssistantTurn:
            results = [m.results[0] for m in call.messages if isinstance(m, ToolResults)]
            if not results or results[-1].is_error:
                return tool_turn(("execute_analysis", COMPARISON))
            return done_turn()

        provider._tool_step = tool_step
        return provider

    report = run_agent([CASES_BY_ID["sales-q3-decline-failed-query"]], retrying)[0]
    assert report.tool_calls == 2
    assert report.scores["recovered"] == 1.0


def test_recovery_case_fails_an_agent_that_gives_up() -> None:
    # The scripted provider never repeats the failed comparison.
    report = run_agent([CASES_BY_ID["sales-q3-decline-failed-query"]], sales_provider)[0]
    assert report.scores["recovered"] == 0.0


def test_follow_up_scoring_requires_the_earlier_scope() -> None:
    region, products = (
        CASES_BY_ID["sales-q3-follow-up-region"],
        CASES_BY_ID["sales-q3-follow-up-products"],
    )
    by_region, by_product = run_agent([region, products], sales_provider)
    assert by_region.scores["context_preserved"] == 1.0
    # The script repeats the regional comparison, so it loses the "that region" scope.
    assert by_product.scores["context_preserved"] == 0.0


def test_report_names_the_model_that_answered(tmp_path: Path) -> None:
    reports = run_agent([CASES_BY_ID["sales-q3-decline"]], sales_provider)
    path = write_report("requested-model", reports, tmp_path / "report.json")
    saved = json.loads(path.read_text())
    assert saved["model"] == "scripted-test"
    assert saved["requested_model"] == "requested-model"
    assert saved["answered_by"] == {"scripted-test": 1}
    case = saved["cases"][0]
    assert case["findings"]
    assert case["chart_count"] == 1
    assert case["interpretation"].startswith("Q3 is July")
    assert case["operations"] == ["period_comparison"]
    assert case["grounding"]["unverified_numbers"] == []


def test_an_answer_without_charts_gets_no_chart_score() -> None:
    def chartless() -> FakeProvider:
        provider = sales_provider()

        def tool_step(call: Call) -> AssistantTurn:
            if any(isinstance(m, ToolResults) for m in call.messages):
                return done_turn()
            return tool_turn(("execute_analysis", COMPARISON))

        provider._tool_step = tool_step
        return provider

    report = run_agent([CASES_BY_ID["sales-q3-decline"]], chartless)[0]
    assert "charts_consistent" not in report.scores


@pytest.mark.parametrize(
    ("value", "percent", "found"),
    [
        (-0.344878, True, True),
        (-34.4878, True, True),
        (-34.4878, False, False),
        (-17.05, True, False),
        (-3448.78, True, False),
    ],
)
def test_a_ratio_may_be_computed_as_a_percentage(value: float, percent: bool, found: bool) -> None:
    # SQL often returns 100 * change; grounding and the text check already accept that form.
    result = StoredResult(
        id="r1",
        tool="execute_sql",
        operation="sql",
        description="change",
        table=TableResult(columns=[], rows=[[value]], row_count=1, truncated=False),
    )
    assert result_contains([result], -0.344878, percent=percent, tolerance=0.01) is found


@pytest.mark.parametrize(
    ("text", "stated"),
    [
        ("June was $280,355.87.", True),
        ("June was about $280,000.", True),
        ("June was $280.4k.", True),
        ("June was $280,355.86.", False),
        ("June was $281,500.00.", False),
        ("June was $279,000.", False),
    ],
)
def test_answers_must_state_figures_at_the_precision_written(text: str, stated: bool) -> None:
    assert text_states(text, 280355.87, percent=False) is stated


def drivers_provider() -> FakeProvider:
    """A model that answers the Q3 question with one change_drivers call and a chart of it."""
    drivers = {"analysis": {**COMPARISON["analysis"], "operation": "change_drivers", "columns": []}}
    drivers["analysis"].pop("breakdown")
    chart = {
        "result_id": "r1",
        "chart_type": "bar",
        "x": "segment",
        "y": ["change"],
        "series": "dimension",
        "title": "Where revenue fell, Q2 to Q3 2024",
    }

    def tool_step(call: Call) -> AssistantTurn:
        turns = sum(1 for m in call.messages if isinstance(m, AssistantTurn))
        steps = [("execute_analysis", drivers), ("create_chart", chart)]
        return tool_turn(steps[turns]) if turns < len(steps) else done_turn()

    def structured(call: Call) -> dict[str, Any]:
        if call.schema is AnalysisPlan:
            return scripted_plan(call)
        prompt = call.messages[0].text  # type: ignore[union-attr]
        line = next(x for x in prompt.splitlines() if x.startswith('{"id": "r1"'))
        result = json.loads(line)
        summary, leads = result["summary"], {}
        for row in result["rows"]:
            leads.setdefault(row[0], row)
        region, product = leads["Region"], leads["Product"]
        return {
            "summary": (
                f"Revenue fell {abs(summary['pct_change']) * 100:.1f}% from Q2 to Q3 2024, "
                f"from ${summary['baseline_total']:,.2f} to ${summary['current_total']:,.2f}. "
                f"{region[1]} and {product[1]} fell far more than their size."
            ),
            "findings": [
                {
                    "statement": f"{region[1]} accounts for {region[6] * 100:.1f}% of the drop "
                    f"but {region[7] * 100:.1f}% of Q2 revenue.",
                    "kind": "fact",
                    "evidence": ["r1"],
                },
                {
                    "statement": f"{product[1]} fell by ${abs(product[4]):,.2f}.",
                    "kind": "fact",
                    "evidence": ["r1"],
                },
            ],
            "caveats": [],
            "chart_ids": ["c1"],
            "follow_up_questions": [],
        }

    return FakeProvider(structured=structured, tool_step=tool_step, model_name="scripted-test")


def test_one_change_drivers_call_finds_both_planted_causes() -> None:
    report = run_agent([CASES_BY_ID["sales-q3-decline"]], drivers_provider)[0]
    assert report.operations == ["change_drivers"]
    assert report.chart_count == 1
    assert report.notes == []
    assert all(score == 1.0 for score in report.scores.values()), report.scores
