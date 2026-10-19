"""Evaluation cases. Every expected figure or entity is computed from the raw data with pandas."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

Frame = pd.DataFrame


@dataclass(frozen=True)
class Truth:
    """A figure the answer should state. ``percent`` means a ratio that may be shown as %."""

    label: str
    # pandas returns numpy scalars; callers convert with float().
    compute: Callable[[Frame], Any]
    percent: bool = False
    relative_tolerance: float = 0.01


@dataclass(frozen=True)
class Case:
    id: str
    dataset: str
    question: str
    category: str
    truths: tuple[Truth, ...] = ()
    # Names that a correct answer mentions (computed from the data). A function may return
    # several acceptable spellings, e.g. ("2024-06", "June").
    entities: tuple[Callable[[Frame], Any], ...] = ()
    # Any of these operations (or "sql") counts as a sensible tool choice.
    expected_operations: tuple[str, ...] = ()
    # Normalized column names the analysis must use.
    expected_columns: tuple[str, ...] = ()
    answerable: bool = True
    expect_interpretation: bool = False
    follow_up_of: str | None = None
    # A typed operation an analyst would run; checked against the truths in tool mode.
    reference: dict[str, Any] | None = None
    limits: dict[str, Any] = field(default_factory=dict)


def _between(frame: Frame, column: str, start: str, end: str) -> Frame:
    return frame[frame[column].between(start, end)]


def _q(frame: Frame, start: str, end: str) -> Frame:
    return _between(frame, "Order Date", start, end)


def _q2(f: Frame) -> Frame:
    return _q(f, "2024-04-01", "2024-06-30")


def _q3(f: Frame) -> Frame:
    return _q(f, "2024-07-01", "2024-09-30")


def _region_change(f: Frame) -> pd.Series:
    return _q3(f).groupby("Region")["Revenue"].sum() - _q2(f).groupby("Region")["Revenue"].sum()


def _west_product_change(f: Frame) -> pd.Series:
    west = f[f["Region"] == "West"]
    return (
        _q3(west).groupby("Product")["Revenue"].sum()
        - _q2(west).groupby("Product")["Revenue"].sum()
    )


def _best_month(frame: Frame) -> tuple[str, ...]:
    monthly = frame.groupby(frame["Order Date"].dt.to_period("M"))["Revenue"].sum()
    best = pd.Period(str(monthly.idxmax()), freq="M")
    return (str(best), best.strftime("%B"))  # "2024-06" or "June"


def _region_revenue_2024(region: str) -> Callable[[Frame], Any]:
    def compute(frame: Frame) -> Any:
        year = _between(frame, "Order Date", "2024-01-01", "2024-12-31")
        return year[year["Region"] == region]["Revenue"].sum()

    return compute


def _median_salary(department: str) -> Callable[[Frame], Any]:
    return lambda frame: frame[frame["Department"] == department]["Salary"].median()


def _iqr_outliers(series: pd.Series) -> int:
    q1, q3 = series.quantile([0.25, 0.75])
    spread = q3 - q1
    return int(((series < q1 - 1.5 * spread) | (series > q3 + 1.5 * spread)).sum())


Q3_COMPARISON = {
    "operation": "period_comparison",
    "date_column": "order_date",
    "metric": {"agg": "sum", "column": "revenue"},
    "baseline": {"start": "2024-04-01", "end": "2024-06-30"},
    "current": {"start": "2024-07-01", "end": "2024-09-30"},
    "breakdown": "region",
}

CASES: list[Case] = [
    Case(
        id="sales-total-by-region-2024",
        dataset="sales",
        question="What was total revenue by region in 2024?",
        category="aggregation",
        truths=tuple(
            Truth(
                f"{region} 2024 revenue",
                _region_revenue_2024(region),
            )
            for region in ("North", "South", "East", "West")
        ),
        entities=(
            lambda f: (
                _between(f, "Order Date", "2024-01-01", "2024-12-31")
                .groupby("Region")["Revenue"]
                .sum()
                .idxmax()
            ),
        ),
        expected_operations=("aggregate", "sql"),
        expected_columns=("region", "revenue", "order_date"),
        reference={
            "operation": "aggregate",
            "group_by": ["region"],
            "metrics": [{"agg": "sum", "column": "revenue"}],
            "filters": [
                {"column": "order_date", "op": "between", "value": ["2024-01-01", "2024-12-31"]}
            ],
        },
    ),
    Case(
        id="sales-top-product",
        dataset="sales",
        question="Which product generated the most revenue overall?",
        category="ranking",
        truths=(
            Truth("top product revenue", lambda f: f.groupby("Product")["Revenue"].sum().max()),
        ),
        entities=(lambda f: f.groupby("Product")["Revenue"].sum().idxmax(),),
        expected_operations=("aggregate", "sql"),
        expected_columns=("product", "revenue"),
        reference={
            "operation": "aggregate",
            "group_by": ["product"],
            "metrics": [{"agg": "sum", "column": "revenue"}],
            "limit": 3,
        },
    ),
    Case(
        id="sales-monthly-trend-2024",
        dataset="sales",
        question="How did monthly revenue change during 2024? Which month was highest?",
        category="trend",
        truths=(
            Truth(
                "highest 2024 monthly revenue",
                lambda f: (
                    _between(f, "Order Date", "2024-01-01", "2024-12-31")
                    .groupby(f["Order Date"].dt.to_period("M"))["Revenue"]
                    .sum()
                    .max()
                ),
            ),
        ),
        entities=(lambda f: _best_month(_between(f, "Order Date", "2024-01-01", "2024-12-31")),),
        expected_operations=("time_series", "sql"),
        expected_columns=("order_date", "revenue"),
        reference={
            "operation": "time_series",
            "date_column": "order_date",
            "grain": "month",
            "metrics": [{"agg": "sum", "column": "revenue"}],
            "start": "2024-01-01",
            "end": "2024-12-31",
        },
    ),
    Case(
        id="sales-q3-decline",
        dataset="sales",
        question="Why did revenue decrease in Q3?",
        category="comparison",
        truths=(
            Truth("Q2 2024 revenue", lambda f: _q2(f)["Revenue"].sum()),
            Truth("Q3 2024 revenue", lambda f: _q3(f)["Revenue"].sum()),
            Truth(
                "Q3 vs Q2 change",
                lambda f: _q3(f)["Revenue"].sum() / _q2(f)["Revenue"].sum() - 1,
                percent=True,
            ),
        ),
        entities=(lambda f: _region_change(f).idxmin(),),
        expected_operations=("period_comparison", "time_series", "aggregate", "sql"),
        expected_columns=("order_date", "revenue"),
        expect_interpretation=True,
        reference=Q3_COMPARISON,
    ),
    Case(
        id="sales-q3-follow-up-region",
        dataset="sales",
        question="Which region contributed most to the decline?",
        category="follow_up",
        follow_up_of="sales-q3-decline",
        truths=(Truth("largest regional drop", lambda f: abs(_region_change(f).min())),),
        entities=(lambda f: _region_change(f).idxmin(),),
        expected_operations=("period_comparison", "aggregate", "sql"),
        expected_columns=("region", "revenue", "order_date"),
        reference=Q3_COMPARISON,
    ),
    Case(
        id="sales-q3-follow-up-products",
        dataset="sales",
        question="Which products were affected most in that region?",
        category="follow_up",
        follow_up_of="sales-q3-follow-up-region",
        entities=(lambda f: _west_product_change(f).idxmin(),),
        truths=(
            Truth("largest product drop in West", lambda f: abs(_west_product_change(f).min())),
        ),
        expected_operations=("period_comparison", "aggregate", "sql"),
        expected_columns=("product", "region", "revenue"),
        reference={
            **Q3_COMPARISON,
            "breakdown": "product",
            "filters": [{"column": "region", "op": "eq", "value": "West"}],
        },
    ),
    Case(
        id="sales-missing-values",
        dataset="sales",
        question="Which columns have missing values, and how many?",
        category="missing_data",
        truths=(
            Truth("missing discounts", lambda f: f["Discount"].isna().sum()),
            Truth("missing sales channels", lambda f: f["Sales Channel"].isna().sum()),
        ),
        expected_operations=("missing_values", "sql", "profile"),
        expected_columns=("discount", "sales_channel"),
        reference={"operation": "missing_values"},
    ),
    Case(
        id="sales-units-revenue-relationship",
        dataset="sales",
        question="Is there a relationship between units sold and revenue per order?",
        category="relationship",
        truths=(
            Truth(
                "units-revenue correlation",
                lambda f: f[["Units", "Revenue"]].corr().loc["Units", "Revenue"],
                relative_tolerance=0.02,
            ),
        ),
        expected_operations=("correlation", "sql"),
        expected_columns=("units", "revenue"),
        reference={"operation": "correlation", "columns": ["units", "revenue"]},
    ),
    Case(
        id="sales-revenue-outliers",
        dataset="sales",
        question="Are there unusually large orders by revenue? How many?",
        category="outliers",
        truths=(Truth("IQR outlier count", lambda f: _iqr_outliers(f["Revenue"])),),
        expected_operations=("outliers", "distribution", "sql"),
        expected_columns=("revenue",),
        reference={"operation": "outliers", "column": "revenue"},
    ),
    Case(
        id="sales-profit-margin-unanswerable",
        dataset="sales",
        question="What was the profit margin by region?",
        category="unanswerable",
        answerable=False,
    ),
    Case(
        id="sales-last-quarter-ambiguous",
        dataset="sales",
        question="How did sales do last quarter?",
        category="ambiguous",
        truths=(
            Truth("Q4 2024 revenue", lambda f: _q(f, "2024-10-01", "2024-12-31")["Revenue"].sum()),
        ),
        expected_operations=("period_comparison", "aggregate", "time_series", "sql"),
        expected_columns=("order_date", "revenue"),
        expect_interpretation=True,
        reference={
            "operation": "aggregate",
            "metrics": [{"agg": "sum", "column": "revenue"}],
            "filters": [
                {"column": "order_date", "op": "between", "value": ["2024-10-01", "2024-12-31"]}
            ],
        },
    ),
    Case(
        id="tickets-slowest-channel",
        dataset="support_tickets",
        question="Which support channel has the slowest average resolution time?",
        category="ranking",
        truths=(
            Truth(
                "slowest channel average hours",
                lambda f: f.groupby("Channel")["Resolution Hours"].mean().max(),
            ),
        ),
        entities=(lambda f: f.groupby("Channel")["Resolution Hours"].mean().idxmax(),),
        expected_operations=("aggregate", "sql"),
        expected_columns=("channel", "resolution_hours"),
        reference={
            "operation": "aggregate",
            "group_by": ["channel"],
            "metrics": [{"agg": "mean", "column": "resolution_hours"}],
        },
    ),
    Case(
        id="tickets-resolution-vs-satisfaction",
        dataset="support_tickets",
        question="Does a longer resolution time go with lower satisfaction?",
        category="relationship",
        truths=(
            Truth(
                "resolution-satisfaction correlation",
                lambda f: f[["Resolution Hours", "Satisfaction"]].dropna().corr().iloc[0, 1],
                relative_tolerance=0.02,
            ),
        ),
        expected_operations=("correlation", "sql"),
        expected_columns=("resolution_hours", "satisfaction"),
        reference={"operation": "correlation", "columns": ["resolution_hours", "satisfaction"]},
    ),
    Case(
        id="tickets-missing-satisfaction",
        dataset="support_tickets",
        question="What share of tickets are missing a satisfaction score?",
        category="missing_data",
        truths=(Truth("missing share", lambda f: f["Satisfaction"].isna().mean(), percent=True),),
        expected_operations=("missing_values", "aggregate", "sql", "profile"),
        expected_columns=("satisfaction",),
        reference={"operation": "missing_values", "columns": ["satisfaction"]},
    ),
    Case(
        id="employees-median-salary",
        dataset="employees",
        question="What is the median salary in each department?",
        category="aggregation",
        truths=tuple(
            Truth(
                f"{d} median salary",
                _median_salary(d),
            )
            for d in ("Engineering", "Sales", "Support", "Finance")
        ),
        expected_operations=("aggregate", "sql"),
        expected_columns=("department", "salary"),
        reference={
            "operation": "aggregate",
            "group_by": ["department"],
            "metrics": [{"agg": "median", "column": "salary"}],
        },
    ),
    Case(
        id="employees-attrition-unanswerable",
        dataset="employees",
        question="What is our employee attrition rate this year?",
        category="unanswerable",
        answerable=False,
    ),
    Case(
        id="sales-q3-decline-tight-limits",
        dataset="sales",
        question="Why did revenue decrease in Q3?",
        category="limits",
        expected_operations=("period_comparison", "time_series", "aggregate", "sql"),
        limits={"max_iterations": 1, "max_tool_calls": 1},
    ),
]

CASES_BY_ID = {case.id: case for case in CASES}
