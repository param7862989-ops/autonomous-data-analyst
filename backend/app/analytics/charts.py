"""Chart specifications built from computed results.

The model chooses the chart's *shape* (type, which columns go on which axis, title). The data
points are always copied from a stored result table, so a chart can never show numbers that
were not computed. The frontend renders the spec with Plotly.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.analytics.engine import AnalyticsError, TableResult
from app.jsonsafe import JsonScalar

ChartType = Literal["line", "bar", "grouped_bar", "stacked_bar", "histogram", "scatter", "heatmap"]

MAX_SERIES = 8  # the size of the categorical palette; colors are never generated
MAX_POINTS = 5_000
MAX_SCATTER_POINTS = 2_000


class ChartError(AnalyticsError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="invalid_chart")


class ChartRequest(BaseModel):
    """What the model asks for. Columns refer to the result table identified by result_id."""

    model_config = ConfigDict(extra="forbid")

    result_id: str = Field(pattern=r"^r\d{1,3}$", description="Id of a previous result, e.g. r2.")
    chart_type: ChartType
    x: str = Field(description="Result column for the x axis (or heatmap columns).")
    y: list[str] = Field(
        min_length=1, max_length=5, description="Numeric result column(s) for the values."
    )
    series: str | None = Field(
        default=None,
        description="Result column whose values become separate lines/bar groups "
        "(for heatmaps: the rows).",
    )
    title: str = Field(min_length=1, max_length=120)
    x_label: str | None = Field(default=None, max_length=80)
    y_label: str | None = Field(default=None, max_length=80)


class ChartTrace(BaseModel):
    name: str
    x: list[JsonScalar]
    y: list[float | None]


class HeatmapData(BaseModel):
    x: list[str]
    y: list[str]
    z: list[list[float | None]]


class ChartSpec(BaseModel):
    # Fields with defaults are always present in responses; say so in the schema.
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: str
    chart_type: ChartType
    title: str
    x_label: str
    y_label: str
    source_result_id: str
    traces: list[ChartTrace] = Field(default_factory=list)
    heatmap: HeatmapData | None = None
    notes: list[str] = Field(default_factory=list)


def _numeric(values: list[JsonScalar], column: str) -> list[float | None]:
    numbers: list[float | None] = []
    for value in values:
        if value is None:
            numbers.append(None)
        elif isinstance(value, bool) or not isinstance(value, int | float):
            raise ChartError(
                f"Column '{column}' is not numeric, so it cannot be plotted as values."
            )
        else:
            numbers.append(float(value))
    return numbers


def _require_columns(table: TableResult, request: ChartRequest) -> None:
    available = {c.name for c in table.columns}
    wanted = [request.x, *request.y] + ([request.series] if request.series else [])
    missing = [c for c in wanted if c not in available]
    if missing:
        raise ChartError(
            f"Result {request.result_id} has no column(s) {', '.join(missing)}. "
            f"Available: {', '.join(sorted(available))}."
        )


def build_chart(request: ChartRequest, table: TableResult, chart_id: str) -> ChartSpec:
    if table.row_count == 0:
        raise ChartError(f"Result {request.result_id} has no rows to chart.")
    _require_columns(table, request)
    notes: list[str] = []
    if table.truncated:
        notes.append("The source result was truncated, so the chart shows only part of it.")

    spec = ChartSpec(
        id=chart_id,
        chart_type=request.chart_type,
        title=request.title,
        x_label=request.x_label or request.x,
        y_label=request.y_label or (request.y[0] if len(request.y) == 1 else "Value"),
        source_result_id=request.result_id,
        notes=notes,
    )

    if request.chart_type == "heatmap":
        spec.heatmap = _heatmap(request, table)
        return spec

    x_values = table.column_values(request.x)
    if request.chart_type == "scatter":
        _numeric(x_values, request.x)
        if len(request.y) != 1:
            raise ChartError("A scatter plot needs exactly one y column.")
        if table.row_count > MAX_SCATTER_POINTS:
            raise ChartError(f"Scatter plots are limited to {MAX_SCATTER_POINTS} points.")

    if request.series:
        if len(request.y) != 1:
            raise ChartError("Use a single y column when splitting by series.")
        spec.traces = _split_by_series(request, table, x_values)
    else:
        spec.traces = [
            ChartTrace(
                name=column, x=list(x_values), y=_numeric(table.column_values(column), column)
            )
            for column in request.y
        ]
    points = sum(len(trace.x) for trace in spec.traces)
    if points > MAX_POINTS:
        raise ChartError(f"The chart would have {points} points; the limit is {MAX_POINTS}.")
    return spec


def _split_by_series(
    request: ChartRequest, table: TableResult, x_values: list[JsonScalar]
) -> list[ChartTrace]:
    assert request.series is not None
    series_values = table.column_values(request.series)
    y_values = _numeric(table.column_values(request.y[0]), request.y[0])
    order: list[str] = []
    traces: dict[str, ChartTrace] = {}
    for x, key, y in zip(x_values, series_values, y_values, strict=True):
        name = "(missing)" if key is None else str(key)
        if name not in traces:
            if len(traces) >= MAX_SERIES:
                raise ChartError(
                    f"'{request.series}' has more than {MAX_SERIES} values; aggregate or filter "
                    "first."
                )
            traces[name] = ChartTrace(name=name, x=[], y=[])
            order.append(name)
        traces[name].x.append(x)
        traces[name].y.append(y)
    return [traces[name] for name in order]


def _heatmap(request: ChartRequest, table: TableResult) -> HeatmapData:
    if not request.series or len(request.y) != 1:
        raise ChartError("A heatmap needs x, series (rows) and exactly one y (cell values).")
    xs = [str(v) for v in table.column_values(request.x)]
    ys = [str(v) for v in table.column_values(request.series)]
    values = _numeric(table.column_values(request.y[0]), request.y[0])
    x_order = list(dict.fromkeys(xs))
    y_order = list(dict.fromkeys(ys))
    if len(x_order) * len(y_order) > MAX_POINTS:
        raise ChartError("The heatmap has too many cells; aggregate first.")
    cells: dict[tuple[str, str], float | None] = {}
    for x, y, value in zip(xs, ys, values, strict=True):
        if (x, y) in cells:
            raise ChartError("Each x/series pair must appear once in a heatmap; aggregate first.")
        cells[(x, y)] = value
    z = [[cells.get((x, y)) for x in x_order] for y in y_order]
    return HeatmapData(x=x_order, y=y_order, z=z)
