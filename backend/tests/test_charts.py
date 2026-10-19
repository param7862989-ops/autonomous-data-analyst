from __future__ import annotations

import pytest

from app.analytics.charts import ChartError, ChartRequest, build_chart
from app.analytics.engine import ResultColumn, TableResult


def table(columns: list[str], rows: list[list[object]], truncated: bool = False) -> TableResult:
    return TableResult(
        columns=[ResultColumn(name=c, type="X") for c in columns],
        rows=rows,  # type: ignore[arg-type]
        row_count=len(rows),
        truncated=truncated,
    )


QUARTERS = table(
    ["period", "region", "revenue"],
    [
        ["2024-Q2", "West", 100.0],
        ["2024-Q3", "West", 40.0],
        ["2024-Q2", "East", 90.0],
        ["2024-Q3", "East", 95.5],
    ],
)


def request(**kwargs: object) -> ChartRequest:
    base: dict[str, object] = {"result_id": "r1", "chart_type": "bar", "title": "Revenue"}
    base.update(kwargs)
    return ChartRequest.model_validate(base)


def test_chart_data_is_copied_from_the_result() -> None:
    spec = build_chart(request(x="period", y=["revenue"], series="region"), QUARTERS, "c1")
    assert spec.source_result_id == "r1"
    assert [t.name for t in spec.traces] == ["West", "East"]
    assert spec.traces[0].x == ["2024-Q2", "2024-Q3"]
    assert spec.traces[0].y == [100.0, 40.0]
    assert spec.traces[1].y == [90.0, 95.5]
    # Every plotted value appears in the source result.
    source = {(r[0], r[1], r[2]) for r in QUARTERS.rows}
    for trace in spec.traces:
        for x, y in zip(trace.x, trace.y, strict=True):
            assert (x, trace.name, y) in source


def test_multiple_y_columns_become_traces() -> None:
    data = table(["month", "a", "b"], [["2024-01", 1, 2], ["2024-02", 3, None]])
    spec = build_chart(request(chart_type="line", x="month", y=["a", "b"]), data, "c1")
    assert [(t.name, t.y) for t in spec.traces] == [("a", [1.0, 3.0]), ("b", [2.0, None])]
    assert spec.y_label == "Value"


def test_heatmap_from_long_correlation_table() -> None:
    corr = table(
        ["column_a", "column_b", "correlation"],
        [["x", "x", 1.0], ["x", "y", 0.5], ["y", "x", 0.5], ["y", "y", 1.0]],
    )
    spec = build_chart(
        request(chart_type="heatmap", x="column_a", series="column_b", y=["correlation"]),
        corr,
        "c2",
    )
    assert spec.heatmap is not None
    assert spec.heatmap.x == ["x", "y"]
    assert spec.heatmap.z == [[1.0, 0.5], [0.5, 1.0]]


def test_truncated_source_is_noted() -> None:
    spec = build_chart(
        request(x="period", y=["revenue"]), QUARTERS.model_copy(update={"truncated": True}), "c1"
    )
    assert spec.notes


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"x": "period", "y": ["profit"]}, "no column"),
        ({"x": "period", "y": ["region"]}, "not numeric"),
        ({"chart_type": "scatter", "x": "period", "y": ["revenue"]}, "not numeric"),
        ({"chart_type": "heatmap", "x": "period", "y": ["revenue"]}, "heatmap needs"),
        ({"x": "period", "y": ["revenue", "revenue"], "series": "region"}, "single y"),
    ],
)
def test_invalid_chart_requests(kwargs: dict[str, object], message: str) -> None:
    with pytest.raises(ChartError, match=message):
        build_chart(request(**kwargs), QUARTERS, "c1")


def test_empty_result_cannot_be_charted() -> None:
    with pytest.raises(ChartError, match="no rows"):
        build_chart(request(x="period", y=["revenue"]), table(["period", "revenue"], []), "c1")


def test_too_many_series() -> None:
    rows = [["2024", f"g{i}", float(i)] for i in range(9)]
    with pytest.raises(ChartError, match="more than 8"):
        build_chart(
            request(x="period", y=["revenue"], series="region"),
            table(["period", "region", "revenue"], rows),
            "c1",
        )


def test_request_schema_rejects_bad_ids() -> None:
    with pytest.raises(ValueError, match="result_id"):
        request(result_id="../r1", x="a", y=["b"])
