"""Analytical correctness: every operation is checked against an independent pandas
computation on the raw sample CSV (ground truth), not against its own SQL.

Ratios (percent change, share of change, correlation) are rounded to 6 decimal places in
results by design, so they are compared with an absolute tolerance of 1e-6."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pandas as pd
import pytest
from pydantic import TypeAdapter, ValidationError

from app.analytics.engine import AnalyticsEngine
from app.analytics.operations import (
    AggregateOp,
    AnalysisOperation,
    CorrelationOp,
    DatasetSchema,
    DistributionOp,
    Filter,
    Metric,
    MissingValuesOp,
    OperationError,
    OutliersOp,
    Period,
    PeriodComparisonOp,
    RowsOp,
    TimeSeriesOp,
)
from tests.factories import SAMPLE_SALES


@pytest.fixture(scope="module")
def truth() -> pd.DataFrame:
    frame = pd.read_csv(SAMPLE_SALES, parse_dates=["Order Date"])
    frame["Sales Channel"] = frame["Sales Channel"].replace("", pd.NA)
    return frame


def as_dict(rows: list[list[Any]], key: int = 0, value: int = 1) -> dict[Any, Any]:
    return {row[key]: row[value] for row in rows}


def test_aggregate_sum_by_region(
    sales_engine: AnalyticsEngine, sales_schema: DatasetSchema, truth: pd.DataFrame
) -> None:
    op = AggregateOp(group_by=["region"], metrics=[Metric(agg="sum", column="revenue")])
    result = op.run(sales_engine, sales_schema)
    expected = truth.groupby("Region")["Revenue"].sum()
    got = as_dict(result.table.rows)
    assert set(got) == set(expected.index)
    for region, total in expected.items():
        assert got[region] == pytest.approx(total)
    # Sorted descending by the metric.
    values = [row[1] for row in result.table.rows]
    assert values == sorted(values, reverse=True)
    assert result.summary == {"group_count": 4, "groups_shown": 4}
    assert result.description == "Sum of Revenue by Region"


def test_aggregate_multiple_metrics_filters_and_limit(
    sales_engine: AnalyticsEngine, sales_schema: DatasetSchema, truth: pd.DataFrame
) -> None:
    op = AggregateOp(
        group_by=["product"],
        metrics=[
            Metric(agg="count"),
            Metric(agg="mean", column="unit_price", alias="avg_price"),
            Metric(agg="count_distinct", column="region"),
        ],
        filters=[
            Filter(column="region", op="in", value=["West", "East"]),
            Filter(column="order_date", op="between", value=["2024-01-01", "2024-12-31"]),
        ],
        sort_by="row_count",
        limit=3,
    )
    result = op.run(sales_engine, sales_schema)
    subset = truth[
        truth["Region"].isin(["West", "East"])
        & truth["Order Date"].between("2024-01-01", "2024-12-31")
    ]
    expected = (
        subset.groupby("Product")
        .agg(n=("Order ID", "count"), price=("Unit Price", "mean"), regions=("Region", "nunique"))
        .sort_values("n", ascending=False)
    )
    assert result.table.row_count == 3
    for product, n, price, regions in result.table.rows:
        assert n == expected.loc[product, "n"]
        assert price == pytest.approx(expected.loc[product, "price"])
        assert regions == expected.loc[product, "regions"]
    assert [row[1] for row in result.table.rows] == list(expected["n"].head(3))
    assert result.summary["group_count"] == 6


def test_time_series_quarterly_revenue(
    sales_engine: AnalyticsEngine, sales_schema: DatasetSchema, truth: pd.DataFrame
) -> None:
    op = TimeSeriesOp(
        date_column="order_date", grain="quarter", metrics=[Metric(agg="sum", column="revenue")]
    )
    result = op.run(sales_engine, sales_schema)
    expected = truth.groupby(truth["Order Date"].dt.to_period("Q"))["Revenue"].sum()
    assert [row[1] for row in result.table.rows] == [
        f"{p.year}-Q{p.quarter}" for p in expected.index
    ]
    assert result.table.rows[0][0] == "2023-01-01"
    for row, total in zip(result.table.rows, expected, strict=True):
        assert row[2] == pytest.approx(total)


def test_time_series_split_by_group_with_date_range(
    sales_engine: AnalyticsEngine, sales_schema: DatasetSchema, truth: pd.DataFrame
) -> None:
    op = TimeSeriesOp(
        date_column="order_date",
        grain="month",
        metrics=[Metric(agg="sum", column="revenue")],
        group_by="region",
        max_groups=2,
        start=dt.date(2024, 7, 1),
        end=dt.date(2024, 9, 30),
    )
    result = op.run(sales_engine, sales_schema)
    window = truth[truth["Order Date"].between("2024-07-01", "2024-09-30")]
    top2 = window.groupby("Region")["Revenue"].sum().nlargest(2).index
    assert {row[2] for row in result.table.rows} == set(top2)
    assert {row[1] for row in result.table.rows} == {"2024-07", "2024-08", "2024-09"}
    for period_start, _, region, total in result.table.rows:
        month = window[
            (window["Region"] == region)
            & (window["Order Date"].dt.strftime("%Y-%m-01") == period_start)
        ]
        assert total == pytest.approx(month["Revenue"].sum())
    assert result.notes


def test_period_comparison_finds_the_planted_q3_decline(
    sales_engine: AnalyticsEngine, sales_schema: DatasetSchema, truth: pd.DataFrame
) -> None:
    op = PeriodComparisonOp(
        date_column="order_date",
        metric=Metric(agg="sum", column="revenue"),
        baseline=Period(start=dt.date(2024, 4, 1), end=dt.date(2024, 6, 30)),
        current=Period(start=dt.date(2024, 7, 1), end=dt.date(2024, 9, 30)),
        breakdown="region",
    )
    result = op.run(sales_engine, sales_schema)
    q2 = truth[truth["Order Date"].between("2024-04-01", "2024-06-30")]
    q3 = truth[truth["Order Date"].between("2024-07-01", "2024-09-30")]
    assert result.summary["baseline_total"] == pytest.approx(q2["Revenue"].sum())
    assert result.summary["current_total"] == pytest.approx(q3["Revenue"].sum())
    total_change = q3["Revenue"].sum() - q2["Revenue"].sum()
    assert result.summary["change"] == pytest.approx(total_change)
    assert result.summary["pct_change"] == pytest.approx(
        total_change / q2["Revenue"].sum(), abs=1e-6
    )

    by_region = q3.groupby("Region")["Revenue"].sum() - q2.groupby("Region")["Revenue"].sum()
    rows = {row[0]: row for row in result.table.rows}
    for region, change in by_region.items():
        assert rows[region][3] == pytest.approx(change)
        assert rows[region][5] == pytest.approx(change / total_change, abs=1e-6)
    # Ground truth story: West is the largest negative contributor.
    assert min(result.table.rows, key=lambda r: r[3])[0] == "West"
    # Shares of change sum to 1 for an additive metric.
    assert sum(row[5] for row in result.table.rows) == pytest.approx(1.0, abs=1e-5)


def test_period_comparison_non_additive_metric_has_no_shares(
    sales_engine: AnalyticsEngine, sales_schema: DatasetSchema, truth: pd.DataFrame
) -> None:
    op = PeriodComparisonOp(
        date_column="order_date",
        metric=Metric(agg="mean", column="revenue"),
        baseline=Period(start=dt.date(2024, 4, 1), end=dt.date(2024, 6, 30)),
        current=Period(start=dt.date(2024, 7, 1), end=dt.date(2024, 9, 30)),
        breakdown="product",
    )
    result = op.run(sales_engine, sales_schema)
    assert all(row[5] is None for row in result.table.rows)
    assert any("not additive" in note for note in result.notes)
    q3 = truth[truth["Order Date"].between("2024-07-01", "2024-09-30")]
    assert result.summary["current_total"] == pytest.approx(q3["Revenue"].mean())


def test_period_comparison_count_without_breakdown(
    sales_engine: AnalyticsEngine, sales_schema: DatasetSchema, truth: pd.DataFrame
) -> None:
    op = PeriodComparisonOp(
        date_column="order_date",
        metric=Metric(agg="count"),
        baseline=Period(start=dt.date(2023, 7, 1), end=dt.date(2023, 9, 30)),
        current=Period(start=dt.date(2024, 7, 1), end=dt.date(2024, 9, 30)),
        filters=[Filter(column="product", op="eq", value="Standing Desk")],
    )
    result = op.run(sales_engine, sales_schema)
    desks = truth[truth["Product"] == "Standing Desk"]
    before = desks["Order Date"].between("2023-07-01", "2023-09-30").sum()
    after = desks["Order Date"].between("2024-07-01", "2024-09-30").sum()
    assert result.table.rows[0][:3] == [before, after, after - before]


def test_distribution_matches_numpy_histogram(
    sales_engine: AnalyticsEngine, sales_schema: DatasetSchema, truth: pd.DataFrame
) -> None:
    import numpy as np

    result = DistributionOp(column="revenue", bins=10).run(sales_engine, sales_schema)
    counts, edges = np.histogram(truth["Revenue"], bins=10)
    assert [row[2] for row in result.table.rows] == list(counts)
    assert [row[0] for row in result.table.rows] == pytest.approx(list(edges[:-1]))
    assert result.summary["median"] == pytest.approx(truth["Revenue"].median())
    assert result.summary["std"] == pytest.approx(truth["Revenue"].std())


def test_correlation_matches_pandas(
    sales_engine: AnalyticsEngine, sales_schema: DatasetSchema, truth: pd.DataFrame
) -> None:
    cols = {"units": "Units", "unit_price": "Unit Price", "revenue": "Revenue"}
    complete = truth[list(cols.values())].dropna()
    for method in ("pearson", "spearman"):
        result = CorrelationOp(columns=list(cols), method=method).run(sales_engine, sales_schema)
        expected = complete.corr(method=method)
        assert len(result.table.rows) == 9
        for a, b, value, n in result.table.rows:
            assert value == pytest.approx(expected.loc[cols[a], cols[b]], abs=1e-6)
            assert n == len(complete)


def test_outliers_iqr_matches_pandas(
    sales_engine: AnalyticsEngine, sales_schema: DatasetSchema, truth: pd.DataFrame
) -> None:
    result = OutliersOp(column="revenue", include_columns=["product"], limit=5).run(
        sales_engine, sales_schema
    )
    q1, q3 = truth["Revenue"].quantile([0.25, 0.75])
    upper = q3 + 1.5 * (q3 - q1)
    lower = q1 - 1.5 * (q3 - q1)
    expected = truth[(truth["Revenue"] > upper) | (truth["Revenue"] < lower)]
    assert result.summary["outlier_count"] == len(expected)
    assert result.summary["upper_bound"] == pytest.approx(upper)
    assert [c.name for c in result.table.columns] == ["product", "revenue"]
    assert result.table.rows[0][1] == pytest.approx(expected["Revenue"].max())


def test_missing_values(
    sales_engine: AnalyticsEngine, sales_schema: DatasetSchema, truth: pd.DataFrame
) -> None:
    result = MissingValuesOp().run(sales_engine, sales_schema)
    rows = {row[0]: row[1] for row in result.table.rows}
    assert rows["discount"] == truth["Discount"].isna().sum()
    assert rows["sales_channel"] == truth["Sales Channel"].isna().sum()
    assert rows["revenue"] == 0


def test_rows_with_contains_filter_escapes_wildcards(
    sales_engine: AnalyticsEngine, sales_schema: DatasetSchema, truth: pd.DataFrame
) -> None:
    result = RowsOp(
        columns=["order_id", "product", "revenue"],
        filters=[Filter(column="product", op="contains", value="desk")],
        sort_by="revenue",
        limit=3,
    ).run(sales_engine, sales_schema)
    desks = truth[truth["Product"].str.contains("desk", case=False)]
    assert result.summary["matching_rows"] == len(desks)
    assert [row[2] for row in result.table.rows] == list(desks["Revenue"].nlargest(3))
    # A literal % must not act as a wildcard.
    none = RowsOp(filters=[Filter(column="product", op="contains", value="%")]).run(
        sales_engine, sales_schema
    )
    assert none.summary["matching_rows"] == 0


def test_filter_values_are_bound_not_interpolated(
    sales_engine: AnalyticsEngine, sales_schema: DatasetSchema
) -> None:
    hostile = "West' OR '1'='1"
    result = AggregateOp(
        metrics=[Metric(agg="count")], filters=[Filter(column="region", op="eq", value=hostile)]
    ).run(sales_engine, sales_schema)
    assert result.table.rows == [[0]]


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"operation": "aggregate", "metrics": [{"agg": "sum", "column": "nope"}]}, "Unknown"),
        ({"operation": "aggregate", "metrics": [{"agg": "sum", "column": "region"}]}, "numeric"),
        (
            {
                "operation": "time_series",
                "date_column": "revenue",
                "grain": "month",
                "metrics": [{"agg": "count"}],
            },
            "datetime",
        ),
        (
            {
                "operation": "aggregate",
                "metrics": [{"agg": "count"}],
                "filters": [{"column": "revenue", "op": "gt", "value": "lots"}],
            },
            "numbers",
        ),
        (
            {
                "operation": "aggregate",
                "metrics": [{"agg": "count"}],
                "filters": [{"column": "region", "op": "gt", "value": "M"}],
            },
            "number or date",
        ),
        (
            {
                "operation": "aggregate",
                "group_by": ['region" ; DROP'],
                "metrics": [{"agg": "count"}],
            },
            "Unknown",
        ),
    ],
)
def test_invalid_operations_raise_clear_errors(
    sales_engine: AnalyticsEngine,
    sales_schema: DatasetSchema,
    payload: dict[str, Any],
    message: str,
) -> None:
    operation = TypeAdapter(AnalysisOperation).validate_python(payload)
    with pytest.raises(OperationError, match=message):
        operation.run(sales_engine, sales_schema)


@pytest.mark.parametrize(
    "payload",
    [
        {"operation": "aggregate", "metrics": []},
        {"operation": "aggregate", "metrics": [{"agg": "sum"}]},
        {"operation": "aggregate", "metrics": [{"agg": "explode", "column": "revenue"}]},
        {"operation": "unknown_op"},
        {"operation": "aggregate", "metrics": [{"agg": "count"}], "limit": 10_000},
        {"operation": "aggregate", "metrics": [{"agg": "count"}], "sql": "DROP TABLE data"},
        {
            "operation": "period_comparison",
            "date_column": "order_date",
            "metric": {"agg": "count"},
            "baseline": {"start": "2024-06-30", "end": "2024-04-01"},
            "current": {"start": "2024-07-01", "end": "2024-09-30"},
        },
    ],
)
def test_schema_rejects_malformed_operations(payload: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(AnalysisOperation).validate_python(payload)
