"""The evaluation harness: tool-mode evals must pass, and agent-mode scoring must tell a correct
answer from a wrong one. (Agent evals against a real model are run separately; see
docs/EVALUATION.md.)"""

from __future__ import annotations

import pytest

from app.agent.llm.fake import FakeProvider
from evals.cases import CASES, CASES_BY_ID
from evals.run import aggregate, run_agent, run_tools
from tests.scripted import sales_provider


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
    assert scores["entity_accuracy"] == 1.0
    assert scores["tool_selection"] == 1.0
    assert scores["grounded"] == 1.0
    assert scores["charts_consistent"] == 1.0
    assert scores["interpretation_stated"] == 1.0
    assert reports[0].notes == []


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
