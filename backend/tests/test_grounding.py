from __future__ import annotations

from typing import Any

import pytest

from app.agent.grounding import check_answer, extract_numbers, feedback_for
from app.agent.schemas import FinalAnswer, StoredResult
from app.analytics.charts import ChartSpec
from app.analytics.engine import ResultColumn, TableResult

RESULT = StoredResult(
    id="r1",
    tool="execute_analysis",
    operation="period_comparison",
    description="Sum of Revenue by Region",
    table=TableResult(
        columns=[ResultColumn(name=n, type="DOUBLE") for n in ["segment", "baseline", "change"]],
        rows=[["West", 100037.77, -63359.08], ["East", 112725.03, 17306.03]],
        row_count=2,
        truncated=False,
    ),
    summary={"baseline_total": 390338.67, "pct_change": -0.344878, "segment_count": 4},
)
CHART = ChartSpec(
    id="c1", chart_type="bar", title="t", x_label="x", y_label="y", source_result_id="r1"
)


def answer(summary: str, findings: list[dict[str, Any]] | None = None, **extra: Any) -> FinalAnswer:
    return FinalAnswer.model_validate(
        {
            "summary": summary,
            "findings": findings or [],
            "caveats": [],
            "chart_ids": [],
            "follow_up_questions": [],
            **extra,
        }
    )


@pytest.mark.parametrize(
    "text",
    [
        "Revenue fell 34.5% overall.",
        "Revenue fell 34% overall.",
        "Revenue fell -34.49%.",
        "West dropped by $63,359.",
        "West dropped by $63,359.08.",
        "West dropped by $63k.",
        "West dropped by 63.4 thousand dollars.",
        "Baseline revenue was $0.39M.",
        "East grew by 17,306.",
        "Across 4 regions in Q3 2024 (2024-07-01 to 2024-09-30), see r1 and c1.",
    ],
)
def test_figures_matching_results_pass(text: str) -> None:
    report = check_answer(answer(text), [RESULT], [CHART])
    assert report.passed, report


@pytest.mark.parametrize(
    ("text", "bad"),
    [
        ("Revenue fell 35.5% overall.", "35.5%"),
        ("West dropped by $64,000.", "$64,000"),
        ("Revenue fell by 12.75 percent.", "12.75 percent"),
        ("West dropped by $70k.", "$70k"),
    ],
)
def test_invented_or_miscalculated_figures_are_flagged(text: str, bad: str) -> None:
    report = check_answer(answer(text), [RESULT], [CHART])
    assert report.unverified_numbers == [bad]
    assert bad in feedback_for(report)


def test_references_and_unsupported_facts() -> None:
    report = check_answer(
        answer(
            "Summary.",
            findings=[
                {"statement": "Cites a ghost.", "kind": "fact", "evidence": ["r7"]},
                {"statement": "Cites nothing.", "kind": "fact", "evidence": []},
                {"statement": "Maybe weather.", "kind": "hypothesis", "evidence": []},
            ],
            chart_ids=["c1", "c9"],
        ),
        [RESULT],
        [CHART],
    )
    assert report.invalid_references == ["c9", "r7"]
    assert report.unsupported_facts == ["Cites a ghost.", "Cites nothing."]
    assert not report.passed


def test_years_counts_and_dates_are_not_checked() -> None:
    tokens = extract_numbers("In 2024 the top 3 of 4 regions, 2024-07-01, Q3, 2024-Q3, r12.")
    assert tokens == []


def test_unicode_minus_and_currency() -> None:
    tokens = extract_numbers("change of " + chr(0x2212) + "63,359 and €1.5M")
    assert [t.value for t in tokens] == [63359.0, 1_500_000.0]
