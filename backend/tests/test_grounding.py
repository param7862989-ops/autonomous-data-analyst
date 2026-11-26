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


@pytest.mark.parametrize(
    "text",
    [
        "From April 1, 2024 to June 30, 2024.",
        "Between 30 June 2024 and Sept. 15th.",
        "On Dec 31 and 1st January.",
    ],
)
def test_dates_with_month_names_are_not_checked(text: str) -> None:
    assert extract_numbers(text) == []


def test_a_figure_next_to_a_month_is_still_checked() -> None:
    assert [t.text for t in extract_numbers("June 30% growth, and June revenue was $280,355.")] == [
        "30%",
        "$280,355",
    ]


def test_unicode_minus_and_currency() -> None:
    tokens = extract_numbers("change of " + chr(0x2212) + "63,359 and €1.5M")
    assert [t.value for t in tokens] == [63359.0, 1_500_000.0]


def named(*names: str) -> StoredResult:
    table = TableResult(
        columns=[ResultColumn(name="segment", type="VARCHAR")],
        rows=[[name] for name in names],
        row_count=len(names),
        truncated=False,
    )
    return RESULT.model_copy(update={"id": "r2", "table": table})


def test_digits_inside_names_from_the_results_are_not_figures() -> None:
    report = check_answer(
        answer("Monitor 27in fell by $63,359 and Model 300 (EU) by 17,306."),
        [RESULT, named("Monitor 27in", "Model 300", "Model 300 (EU)")],
        [],
    )
    assert report.passed, report
    assert report.checked_numbers == 2


@pytest.mark.parametrize(
    ("cell", "text", "bad"),
    [
        ("5,000,000", "Revenue was 5,000,000.", "5,000,000"),  # not a name
        ("$5M", "Revenue was $5M.", "$5M"),  # not a name
        ("Monitor 27in", "Revenue fell by 27%.", "27%"),  # not that name
        ("Model 300", "Model 3000 sold well.", "3000"),  # only whole names
    ],
)
def test_names_cannot_hide_invented_figures(cell: str, text: str, bad: str) -> None:
    assert check_answer(answer(text), [RESULT, named(cell)], []).unverified_numbers == [bad]


JUNE = StoredResult(
    id="r1",
    tool="execute_sql",
    operation="sql",
    description="Monthly revenue",
    table=TableResult(
        columns=[ResultColumn(name="revenue", type="DOUBLE")],
        rows=[[280355.87], [0.344878]],
        row_count=2,
        truncated=False,
    ),
)


@pytest.mark.parametrize(
    "text",
    [
        "June revenue was $280,355.87.",
        "June revenue was $280,356.",
        "June revenue was about $280,000.",
        "June revenue was $280.4k.",
        "June revenue was $0.28M.",
        "Revenue fell 34.49%.",
        "Revenue fell 34%.",
    ],
)
def test_figures_rounded_as_written_pass(text: str) -> None:
    assert check_answer(answer(text), [JUNE], []).passed


@pytest.mark.parametrize(
    ("text", "bad"),
    [
        # Each is within 0.5% of 280,355.87; the precision written says it is wrong.
        ("June revenue was $280,355.86.", "$280,355.86"),
        ("June revenue was $281,500.00.", "$281,500.00"),
        ("June revenue was $279,000.", "$279,000"),
        ("June revenue was $281,000.", "$281,000"),
        ("Revenue fell 34.48%.", "34.48%"),
        ("Revenue fell 30%.", "30%"),
    ],
)
def test_figures_wrong_at_the_precision_written_are_flagged(text: str, bad: str) -> None:
    assert check_answer(answer(text), [JUNE], []).unverified_numbers == [bad]
