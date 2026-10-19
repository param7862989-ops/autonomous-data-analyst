"""A scripted analysis of the sample sales dataset, used by API tests and the E2E server.

It behaves like a careful model would for "why did revenue fall in Q3": compare Q2 and Q3 2024
by region, chart the change, then answer using only numbers from the computed result. The
numbers in the answer are read from the actual result at answer time, never hardcoded.
"""

from __future__ import annotations

import json
from concurrent.futures import Executor, Future
from typing import Any

from app.agent.llm.base import AssistantTurn, ToolResults
from app.agent.llm.fake import Call, FakeProvider, done_turn, tool_turn
from app.agent.schemas import AnalysisPlan

QUESTION = "Why did revenue decrease in Q3?"

COMPARISON = {
    "analysis": {
        "operation": "period_comparison",
        "date_column": "order_date",
        "metric": {"agg": "sum", "column": "revenue"},
        "baseline": {"start": "2024-04-01", "end": "2024-06-30"},
        "current": {"start": "2024-07-01", "end": "2024-09-30"},
        "breakdown": "region",
    }
}


def _plan(call: Call) -> dict[str, Any]:
    return {
        "intent": "comparison",
        "answerable": True,
        "relevant_columns": ["order_date", "revenue", "region"],
        "interpretation": "Q3 is July to September 2024, compared with Q2 2024.",
        "steps": [
            {"description": "Compare Q2 and Q3 2024 revenue by region", "tool": "execute_analysis"},
            {"description": "Chart the change by region", "tool": "create_chart"},
        ],
    }


def _last_result(call: Call) -> dict[str, Any] | None:
    for message in reversed(call.messages):
        if isinstance(message, ToolResults):
            for outcome in message.results:
                if not outcome.is_error and outcome.content.startswith("{"):
                    payload: dict[str, Any] = json.loads(outcome.content)
                    if "result_id" in payload:
                        return payload
    return None


def _tool_step(call: Call) -> AssistantTurn:
    turns = sum(1 for m in call.messages if isinstance(m, AssistantTurn))
    if turns == 0:
        return tool_turn(("execute_analysis", COMPARISON))
    if turns == 1:
        result = _last_result(call)
        result_id = result["result_id"] if result else "r1"
        return tool_turn(
            (
                "create_chart",
                {
                    "result_id": result_id,
                    "chart_type": "bar",
                    "x": "segment",
                    "y": ["change"],
                    "title": "Change in revenue by region, Q2 to Q3 2024",
                    "y_label": "Revenue change",
                },
            )
        )
    return done_turn()


def _answer(call: Call) -> dict[str, Any]:
    prompt = call.messages[0].text  # type: ignore[union-attr]
    blocks = [line for line in prompt.splitlines() if line.startswith('{"id": "r')]
    result = json.loads(blocks[0]) if blocks else None
    if result is None:
        return {
            "summary": "No results were computed, so the question could not be answered.",
            "findings": [],
            "caveats": [],
            "chart_ids": [],
            "follow_up_questions": [],
        }
    summary = result["summary"]
    worst = min(result["rows"], key=lambda row: row[3])
    return {
        "summary": (
            f"Revenue fell from ${summary['baseline_total']:,.0f} in Q2 2024 to "
            f"${summary['current_total']:,.0f} in Q3 2024, a change of "
            f"{summary['pct_change'] * 100:.1f}%. {worst[0]} contributed most of the decline."
        ),
        "findings": [
            {
                "statement": f"{worst[0]} revenue fell by ${abs(worst[3]):,.0f}, the largest "
                "drop of any region.",
                "kind": "fact",
                "evidence": [result["id"]],
            },
            {
                "statement": f"A smaller order volume in {worst[0]} may explain the drop; order "
                "counts were not compared.",
                "kind": "hypothesis",
                "evidence": [],
            },
        ],
        "caveats": ["Q3 was interpreted as July to September 2024."],
        "chart_ids": ["c1"],
        "follow_up_questions": [f"Which products drove the decline in {worst[0]}?"],
    }


def sales_provider() -> FakeProvider:
    def structured(call: Call) -> dict[str, Any]:
        return _plan(call) if call.schema is AnalysisPlan else _answer(call)

    return FakeProvider(structured=structured, tool_step=_tool_step, model_name="scripted-test")


class InlineExecutor(Executor):
    """Runs submitted work immediately, in the caller's thread (deterministic tests)."""

    def submit(self, fn, /, *args, **kwargs):  # type: ignore[no-untyped-def, override]
        future: Future[Any] = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except Exception as exc:  # noqa: BLE001
            future.set_exception(exc)
        return future


class HoldingExecutor(Executor):
    """Accepts work but never runs it (to observe queued runs)."""

    def __init__(self) -> None:
        self.held: list[tuple[Any, tuple[Any, ...]]] = []

    def submit(self, fn, /, *args, **kwargs):  # type: ignore[no-untyped-def, override]
        self.held.append((fn, args))
        return Future()
