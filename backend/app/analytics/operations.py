"""Typed analytical operations, compiled to SQL against the sandboxed ``data`` table.

These are the preferred way for the agent to compute anything. Every column name is checked
against the dataset schema (and its type) and then quoted; every value goes in as a bound
parameter; enumerations (aggregations, time grains) come from fixed literals. Nothing the model
writes is ever pasted into SQL text.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.analytics.engine import (
    TABLE_NAME,
    AnalyticsError,
    QueryEngine,
    ResultColumn,
    TableResult,
)
from app.jsonsafe import JsonScalar

SemanticType = Literal["numeric", "datetime", "boolean", "categorical", "text"]
Aggregation = Literal["sum", "mean", "median", "min", "max", "count", "count_distinct", "std"]
TimeGrain = Literal["day", "week", "month", "quarter", "year"]
FilterOp = Literal[
    "eq", "ne", "gt", "gte", "lt", "lte", "in", "not_in", "between", "is_null", "not_null",
    "contains",
]  # fmt: skip
Scalar = str | int | float | bool
ALIAS_PATTERN = r"^[a-z][a-z0-9_]{0,40}$"

_AGG_SQL: dict[str, str] = {
    "sum": "SUM({})",
    "mean": "AVG({})",
    "median": "MEDIAN({})",
    "min": "MIN({})",
    "max": "MAX({})",
    "count": "COUNT({})",
    "count_distinct": "COUNT(DISTINCT {})",
    "std": "STDDEV_SAMP({})",
}
_AGG_LABEL = {
    "sum": "Sum",
    "mean": "Average",
    "median": "Median",
    "min": "Minimum",
    "max": "Maximum",
    "count": "Count",
    "count_distinct": "Distinct count",
    "std": "Standard deviation",
}
_NUMERIC_AGGS = {"sum", "mean", "median", "std"}
_ADDITIVE_AGGS = {"sum", "count"}
MAX_DRIVER_COLUMNS = 8
MAX_DRIVER_SEGMENTS = 50
_PERIOD_LABEL_SQL = {
    "day": "STRFTIME({p}, '%Y-%m-%d')",
    "week": "STRFTIME({p}, '%G-W%V')",
    "month": "STRFTIME({p}, '%Y-%m')",
    "quarter": "CAST(YEAR({p}) AS VARCHAR) || '-Q' || CAST(QUARTER({p}) AS VARCHAR)",
    "year": "STRFTIME({p}, '%Y')",
}


class OperationError(AnalyticsError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="invalid_operation")


# --- Schema ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class ColumnSpec:
    name: str
    semantic_type: SemanticType
    original_name: str


class DatasetSchema:
    def __init__(self, columns: list[ColumnSpec]) -> None:
        self.columns = columns
        self._by_name = {column.name: column for column in columns}

    def get(
        self, name: str, *, allowed: set[str] | None = None, role: str = "column"
    ) -> ColumnSpec:
        column = self._by_name.get(name)
        if column is None:
            available = ", ".join(c.name for c in self.columns)
            raise OperationError(f"Unknown column '{name}'. Available columns: {available}.")
        if allowed is not None and column.semantic_type not in allowed:
            kinds = " or ".join(sorted(allowed))
            raise OperationError(
                f"The {role} '{name}' must be {kinds}, but it is {column.semantic_type}."
            )
        return column

    def label(self, name: str) -> str:
        column = self._by_name.get(name)
        return column.original_name if column else name


def quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


# --- Shared building blocks ------------------------------------------------------------------


class Metric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agg: Aggregation = Field(description="Aggregation to apply.")
    column: str | None = Field(
        default=None,
        description="Column to aggregate. Omit only with agg='count' to count rows.",
    )
    alias: str | None = Field(
        default=None,
        pattern=ALIAS_PATTERN,
        description="Optional output column name (lowercase snake_case).",
    )

    @model_validator(mode="after")
    def _column_required(self) -> Metric:
        if self.column is None and self.agg != "count":
            raise ValueError(f"agg='{self.agg}' needs a column")
        return self

    @property
    def output_name(self) -> str:
        if self.alias:
            return self.alias
        return "row_count" if self.column is None else f"{self.agg}_{self.column}"


class Filter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    column: str
    op: FilterOp
    value: Scalar | list[Scalar] | None = Field(
        default=None,
        description=(
            "Comparison value. A list for 'in'/'not_in', a [low, high] pair for 'between', "
            "omitted for 'is_null'/'not_null'. Dates as ISO strings (YYYY-MM-DD)."
        ),
    )


class Period(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: dt.date = Field(description="First day of the period (inclusive).")
    end: dt.date = Field(description="Last day of the period (inclusive).")

    @model_validator(mode="after")
    def _ordered(self) -> Period:
        if self.end < self.start:
            raise ValueError("period end is before its start")
        return self

    def label(self) -> str:
        return f"{self.start.isoformat()} to {self.end.isoformat()}"

    def bounds(self) -> tuple[str, str]:
        """Half-open [start, end + 1 day) as ISO strings."""
        return self.start.isoformat(), (self.end + dt.timedelta(days=1)).isoformat()


class _Compiler:
    def __init__(self, schema: DatasetSchema) -> None:
        self.schema = schema

    def metric(self, metric: Metric, inner: str | None = None) -> str:
        """SQL for an aggregate. ``inner`` replaces the column expression (e.g. a CASE)."""
        if metric.column is None:
            return "COUNT(*)" if inner is None else f"COUNT({inner})"
        allowed = {"numeric"} if metric.agg in _NUMERIC_AGGS else None
        if metric.agg in {"min", "max"}:
            allowed = {"numeric", "datetime"}
        column = self.schema.get(metric.column, allowed=allowed, role=f"{metric.agg} column")
        expression = inner if inner is not None else quote(column.name)
        return _AGG_SQL[metric.agg].format(expression)

    def metric_label(self, metric: Metric) -> str:
        if metric.column is None:
            return "Row count"
        return f"{_AGG_LABEL[metric.agg]} of {self.schema.label(metric.column)}"

    def filters(self, filters: list[Filter]) -> tuple[list[str], list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        for item in filters:
            sql, values = self._filter(item)
            clauses.append(sql)
            params.extend(values)
        return clauses, params

    def _value(self, column: ColumnSpec, value: Any) -> Any:
        if isinstance(value, list):
            raise OperationError(f"Filter on '{column.name}' expects a single value, not a list.")
        kind = column.semantic_type
        if kind == "numeric":
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise OperationError(f"Filter values for '{column.name}' must be numbers.")
            return value
        if kind == "datetime":
            try:
                return dt.datetime.fromisoformat(str(value))
            except ValueError as exc:
                raise OperationError(
                    f"Filter values for '{column.name}' must be ISO dates like 2024-07-01."
                ) from exc
        if kind == "boolean":
            if not isinstance(value, bool):
                raise OperationError(f"Filter values for '{column.name}' must be true or false.")
            return value
        return str(value)

    def _filter(self, item: Filter) -> tuple[str, list[Any]]:
        column = self.schema.get(item.column, role="filter column")
        name = quote(column.name)
        op = item.op
        if op == "is_null":
            return f"{name} IS NULL", []
        if op == "not_null":
            return f"{name} IS NOT NULL", []
        if item.value is None:
            raise OperationError(f"Filter '{op}' on '{column.name}' needs a value.")
        if op in {"in", "not_in"}:
            values = item.value if isinstance(item.value, list) else [item.value]
            if not values or len(values) > 100:
                raise OperationError("'in' filters need between 1 and 100 values.")
            converted = [self._value(column, v) for v in values]
            placeholders = ", ".join("?" for _ in converted)
            keyword = "IN" if op == "in" else "NOT IN"
            return f"{name} {keyword} ({placeholders})", converted
        if op == "between":
            if not isinstance(item.value, list) or len(item.value) != 2:
                raise OperationError("'between' needs a [low, high] pair.")
            low, high = (self._value(column, v) for v in item.value)
            return f"{name} BETWEEN ? AND ?", [low, high]
        if op == "contains":
            if column.semantic_type not in {"categorical", "text"}:
                raise OperationError("'contains' only works on text columns.")
            text = str(item.value)
            escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            return f"{name} ILIKE ? ESCAPE '\\'", [f"%{escaped}%"]
        if op in {"gt", "gte", "lt", "lte"} and column.semantic_type not in {"numeric", "datetime"}:
            raise OperationError(
                f"'{op}' needs a number or date column; '{column.name}' isn't one."
            )
        sql_op = {"eq": "=", "ne": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}[op]
        return f"{name} {sql_op} ?", [self._value(column, item.value)]


def _where(clauses: list[str]) -> str:
    return f" WHERE {' AND '.join(clauses)}" if clauses else ""


def _filter_note(schema: DatasetSchema, filters: list[Filter]) -> str:
    if not filters:
        return ""
    parts = []
    for item in filters:
        value = "" if item.value is None else f" {item.value}"
        parts.append(f"{schema.label(item.column)} {item.op}{value}")
    return f" (where {'; '.join(parts)})"


class OperationResult(BaseModel):
    operation: str
    description: str
    table: TableResult
    summary: dict[str, JsonScalar] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


def _round(value: float | None, digits: int = 6) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return round(value, digits)


def _ratio(value: float | None) -> float | None:
    """Ratios keep more digits: they get rounded again when written as a percentage, and rounding
    0.17054981 to 0.170550 first turns 17.05% into 17.06%."""
    return _round(value, 10)


# --- Operations ------------------------------------------------------------------------------


class AggregateOp(BaseModel):
    """Group rows and compute metrics: totals, averages, counts, rankings, breakdowns."""

    model_config = ConfigDict(extra="forbid")

    operation: Literal["aggregate"] = "aggregate"
    group_by: list[str] = Field(default_factory=list, max_length=3)
    metrics: list[Metric] = Field(min_length=1, max_length=5)
    filters: list[Filter] = Field(default_factory=list, max_length=10)
    sort_by: str | None = Field(default=None, description="A group_by column or metric name.")
    descending: bool = True
    limit: int = Field(default=50, ge=1, le=500)

    def run(self, engine: QueryEngine, schema: DatasetSchema) -> OperationResult:
        compiler = _Compiler(schema)
        groups = [quote(schema.get(g, role="group_by column").name) for g in self.group_by]
        names = [m.output_name for m in self.metrics]
        if len(set(names)) != len(names) or set(names) & set(self.group_by):
            raise OperationError("Metric names must be unique; set distinct aliases.")
        selects = groups + [f"{compiler.metric(m)} AS {quote(m.output_name)}" for m in self.metrics]
        clauses, params = compiler.filters(self.filters)
        sort = self.sort_by or names[0]
        if sort not in names and sort not in self.group_by:
            raise OperationError(f"sort_by must be one of: {', '.join(self.group_by + names)}.")
        direction = "DESC" if self.descending else "ASC"
        group_sql = f" GROUP BY {', '.join(groups)}" if groups else ""
        sql = (
            f"SELECT {', '.join(selects)} FROM {TABLE_NAME}{_where(clauses)}{group_sql} "
            f"ORDER BY {quote(sort)} {direction} NULLS LAST LIMIT {self.limit}"
        )
        table = engine.execute(sql, params)
        summary: dict[str, JsonScalar] = {}
        if groups:
            count_sql = (
                f"SELECT COUNT(*) FROM (SELECT 1 FROM {TABLE_NAME}{_where(clauses)}{group_sql})"
            )
            total_groups = engine.execute(count_sql, params).rows[0][0]
            summary["group_count"] = total_groups
            summary["groups_shown"] = table.row_count
        metric_labels = ", ".join(compiler.metric_label(m) for m in self.metrics)
        by = f" by {', '.join(schema.label(g) for g in self.group_by)}" if self.group_by else ""
        return OperationResult(
            operation=self.operation,
            description=f"{metric_labels}{by}{_filter_note(schema, self.filters)}",
            table=table,
            summary=summary,
        )


class TimeSeriesOp(BaseModel):
    """Metrics per time period (day/week/month/quarter/year), optionally split by a column."""

    model_config = ConfigDict(extra="forbid")

    operation: Literal["time_series"] = "time_series"
    date_column: str
    grain: TimeGrain
    metrics: list[Metric] = Field(min_length=1, max_length=5)
    group_by: str | None = Field(default=None, description="Optional column to split series by.")
    max_groups: int = Field(default=10, ge=1, le=20, description="Keep the top N groups.")
    start: dt.date | None = None
    end: dt.date | None = Field(default=None, description="Inclusive last day.")
    filters: list[Filter] = Field(default_factory=list, max_length=10)

    def run(self, engine: QueryEngine, schema: DatasetSchema) -> OperationResult:
        compiler = _Compiler(schema)
        date = quote(schema.get(self.date_column, allowed={"datetime"}, role="date column").name)
        clauses, params = compiler.filters(self.filters)
        clauses.insert(0, f"{date} IS NOT NULL")
        if self.start:
            clauses.append(f"{date} >= ?")
            params.append(dt.datetime.combine(self.start, dt.time()))
        if self.end:
            clauses.append(f"{date} < ?")
            params.append(dt.datetime.combine(self.end + dt.timedelta(days=1), dt.time()))
        period = f"DATE_TRUNC('{self.grain}', {date})"
        label = _PERIOD_LABEL_SQL[self.grain].format(p=period)
        selects = [f"CAST({period} AS DATE) AS period_start", f"{label} AS period"]
        group_cols = ["period_start", "period"]
        notes: list[str] = []
        group_params: list[Any] = []
        if self.group_by:
            group = quote(schema.get(self.group_by, role="group_by column").name)
            selects.append(group)
            group_cols.append(group)
            first = compiler.metric(self.metrics[0])
            top_sql = (
                f"SELECT {group} FROM {TABLE_NAME}{_where(clauses)} GROUP BY {group} "
                f"ORDER BY {first} DESC NULLS LAST LIMIT {self.max_groups}"
            )
            clauses = [*clauses, f"{group} IN ({top_sql})"]
            group_params = list(params)
            notes.append(
                f"Series limited to the top {self.max_groups} values of "
                f"{schema.label(self.group_by)} by {compiler.metric_label(self.metrics[0])}."
            )
        selects += [f"{compiler.metric(m)} AS {quote(m.output_name)}" for m in self.metrics]
        sql = (
            f"SELECT {', '.join(selects)} FROM {TABLE_NAME}{_where(clauses)} "
            f"GROUP BY {', '.join(group_cols)} ORDER BY {', '.join(group_cols)}"
        )
        table = engine.execute(sql, params + group_params)
        metric_labels = ", ".join(compiler.metric_label(m) for m in self.metrics)
        split = f" by {schema.label(self.group_by)}" if self.group_by else ""
        return OperationResult(
            operation=self.operation,
            description=(
                f"{metric_labels} per {self.grain}{split}{_filter_note(schema, self.filters)}"
            ),
            table=table,
            notes=notes,
        )


class PeriodComparisonOp(BaseModel):
    """Compare a metric between two date ranges, optionally broken down by a column, with each
    segment's change and its share of the total change (contribution analysis)."""

    model_config = ConfigDict(extra="forbid")

    operation: Literal["period_comparison"] = "period_comparison"
    date_column: str
    metric: Metric
    baseline: Period = Field(description="The earlier/reference period.")
    current: Period = Field(description="The period being explained.")
    breakdown: str | None = Field(default=None, description="Optional segment column.")
    filters: list[Filter] = Field(default_factory=list, max_length=10)
    limit: int = Field(default=25, ge=1, le=200, description="Segments with the largest change.")

    def run(self, engine: QueryEngine, schema: DatasetSchema) -> OperationResult:
        compiler = _Compiler(schema)
        query = _TwoPeriods.build(
            compiler, self.date_column, self.metric, self.baseline, self.current, self.filters
        )
        base_total, cur_total, total_change = query.totals(engine)
        additive = self.metric.agg in _ADDITIVE_AGGS
        summary: dict[str, JsonScalar] = {
            "baseline_period": self.baseline.label(),
            "current_period": self.current.label(),
            "baseline_total": _round(base_total),
            "current_total": _round(cur_total),
            "change": _round(total_change),
            "pct_change": _pct(base_total, total_change),
        }
        notes: list[str] = []
        if not additive and self.breakdown:
            notes.append(
                f"{_AGG_LABEL[self.metric.agg]} is not additive, so segment changes do not sum "
                "to the total change and no contribution shares are given."
            )

        columns = ["baseline", "current", "change", "pct_change", "share_of_change"]
        if self.breakdown:
            column = schema.get(self.breakdown, role="breakdown column")
            changes, truncated = query.segments(engine, column.name)
            if truncated:
                notes.append("The breakdown has more segments than could be compared.")
            rows: list[list[JsonScalar]] = [
                [s.segment, _round(s.baseline), _round(s.current), _round(s.change), s.pct, share]
                for s in changes
                for share in [s.share_of(total_change) if additive else None]
            ]
            segment_count = len(rows)
            summary["segment_count"] = segment_count
            rows = rows[: self.limit]
            table = TableResult(
                columns=[ResultColumn(name="segment", type="VARCHAR")]
                + [ResultColumn(name=c, type="DOUBLE") for c in columns],
                rows=rows,
                row_count=len(rows),
                truncated=segment_count > len(rows),
            )
        else:
            table = TableResult(
                columns=[ResultColumn(name=c, type="DOUBLE") for c in columns],
                rows=[
                    [
                        summary["baseline_total"],
                        summary["current_total"],
                        summary["change"],
                        summary["pct_change"],
                        1.0 if additive and total_change else None,
                    ]
                ],
                row_count=1,
                truncated=False,
            )
        split = f" by {schema.label(self.breakdown)}" if self.breakdown else ""
        return OperationResult(
            operation=self.operation,
            description=(
                f"{compiler.metric_label(self.metric)}: {self.baseline.label()} vs "
                f"{self.current.label()}{split}{_filter_note(schema, self.filters)}"
            ),
            table=table,
            summary=summary,
            notes=notes,
        )


@dataclass(frozen=True)
class _SegmentChange:
    segment: JsonScalar
    baseline: float | None
    current: float | None

    @property
    def change(self) -> float | None:
        if self.baseline is None or self.current is None:
            return None
        return self.current - self.baseline

    @property
    def pct(self) -> float | None:
        return _pct(self.baseline, self.change)

    def share_of(self, total_change: float | None) -> float | None:
        change = self.change
        return _ratio(change / total_change) if change is not None and total_change else None


@dataclass(frozen=True)
class _TwoPeriods:
    """SQL pieces for one metric over two date ranges (one scan computes both)."""

    agg: str
    base_expr: str
    cur_expr: str
    clauses: list[str]
    select_params: list[Any]
    where_params: list[Any]

    @classmethod
    def build(
        cls,
        compiler: _Compiler,
        date_column: str,
        metric: Metric,
        baseline: Period,
        current: Period,
        filters: list[Filter],
    ) -> _TwoPeriods:
        schema = compiler.schema
        date = quote(schema.get(date_column, allowed={"datetime"}, role="date column").name)
        value = "1" if metric.column is None else quote(schema.get(metric.column).name)
        base_start, base_end = baseline.bounds()
        cur_start, cur_end = current.bounds()
        # One template for both periods; the bound parameters decide which period each
        # aggregate (and each half of the WHERE clause) covers.
        in_range = f"{date} >= CAST(? AS TIMESTAMP) AND {date} < CAST(? AS TIMESTAMP)"
        clauses, filter_params = compiler.filters(filters)
        clauses.append(f"(({in_range}) OR ({in_range}))")
        return cls(
            agg=metric.agg,
            base_expr=compiler.metric(metric, f"CASE WHEN {in_range} THEN {value} END"),
            cur_expr=compiler.metric(metric, f"CASE WHEN {in_range} THEN {value} END"),
            clauses=clauses,
            select_params=[base_start, base_end, cur_start, cur_end],
            where_params=[*filter_params, base_start, base_end, cur_start, cur_end],
        )

    @property
    def _params(self) -> list[Any]:
        return self.select_params + self.where_params

    def totals(self, engine: QueryEngine) -> tuple[float | None, float | None, float | None]:
        sql = (
            f"SELECT {self.base_expr} AS baseline, {self.cur_expr} AS current "
            f"FROM {TABLE_NAME}{_where(self.clauses)}"
        )
        row = engine.execute(sql, self._params).rows[0]
        base, cur = _as_float(row[0], self.agg), _as_float(row[1], self.agg)
        change = cur - base if cur is not None and base is not None else None
        return base, cur, change

    def segments(self, engine: QueryEngine, column: str) -> tuple[list[_SegmentChange], bool]:
        """Per-segment values, largest absolute change first, and whether rows were capped."""
        segment = quote(column)
        sql = (
            f"SELECT {segment} AS segment, {self.base_expr} AS baseline, "
            f"{self.cur_expr} AS current FROM {TABLE_NAME}{_where(self.clauses)} "
            f"GROUP BY {segment}"
        )
        raw = engine.execute(sql, self._params)
        changes = [
            _SegmentChange(seg, _as_float(base, self.agg), _as_float(cur, self.agg))
            for seg, base, cur in raw.rows
        ]
        changes.sort(key=lambda s: abs(s.change) if s.change is not None else -1, reverse=True)
        return changes, raw.truncated

    def distinct_counts(self, engine: QueryEngine, columns: list[str]) -> list[int]:
        counts = ", ".join(f"COUNT(DISTINCT {quote(c)})" for c in columns)
        sql = f"SELECT {counts} FROM {TABLE_NAME}{_where(self.clauses)}"
        row = engine.execute(sql, self.where_params).rows[0]
        return [n if isinstance(n, int) and not isinstance(n, bool) else 0 for n in row]


class ChangeDriversOp(BaseModel):
    """Explain a change between two date ranges across several segment columns at once.

    For an additive metric (sum or count), each segment gets its change, its share of the total
    change and its share of the baseline. ``share_gap`` is the difference: a segment that moved
    only as much as its size predicts has a gap near zero, so the columns are ranked by their
    largest gap. A large gap locates a change; it does not explain why it happened.
    """

    model_config = ConfigDict(extra="forbid")

    operation: Literal["change_drivers"] = "change_drivers"
    date_column: str
    metric: Metric
    baseline: Period = Field(description="The earlier/reference period.")
    current: Period = Field(description="The period being explained.")
    columns: list[str] = Field(
        default_factory=list,
        max_length=MAX_DRIVER_COLUMNS,
        description=(
            "Segment columns to compare. Empty means every categorical or boolean column with "
            f"2 to {MAX_DRIVER_SEGMENTS} distinct values."
        ),
    )
    filters: list[Filter] = Field(default_factory=list, max_length=10)
    top: int = Field(
        default=3, ge=1, le=10, description="Segments shown per column, largest change first."
    )

    def run(self, engine: QueryEngine, schema: DatasetSchema) -> OperationResult:
        if self.metric.agg not in _ADDITIVE_AGGS:
            raise OperationError(
                "change_drivers needs an additive metric (sum or count). For averages or "
                "medians, use period_comparison with a breakdown."
            )
        compiler = _Compiler(schema)
        query = _TwoPeriods.build(
            compiler, self.date_column, self.metric, self.baseline, self.current, self.filters
        )
        base_total, cur_total, total_change = query.totals(engine)
        notes: list[str] = []

        if self.columns:
            names = [
                schema.get(
                    c, allowed={"categorical", "boolean", "text"}, role="segment column"
                ).name
                for c in dict.fromkeys(self.columns)
            ]
        else:
            names = [
                c.name
                for c in schema.columns
                if c.semantic_type in {"categorical", "boolean"} and c.name != self.date_column
            ][:MAX_DRIVER_COLUMNS]
        counts = query.distinct_counts(engine, names) if names else []
        usable = [n for n, k in zip(names, counts, strict=True) if 2 <= k <= MAX_DRIVER_SEGMENTS]
        skipped = [schema.label(n) for n in names if n not in usable]
        if skipped:
            notes.append(
                f"Not compared (fewer than 2 or more than {MAX_DRIVER_SEGMENTS} values): "
                + ", ".join(skipped)
                + "."
            )
        if not usable:
            raise OperationError(
                f"No segment column has 2 to {MAX_DRIVER_SEGMENTS} values in these periods."
            )
        if not total_change:
            notes.append("The total did not change, so there are no shares of the change.")

        dimensions = []
        for name in usable:
            changes, truncated = query.segments(engine, name)
            if truncated:
                notes.append(f"{schema.label(name)} has more segments than could be compared.")
            rows: list[list[JsonScalar]] = []
            for s in changes:
                share = s.share_of(total_change)
                size = (
                    _ratio(s.baseline / base_total)
                    if s.baseline is not None and base_total
                    else None
                )
                gap = _ratio(share - size) if share is not None and size is not None else None
                rows.append(
                    [
                        schema.label(name),
                        s.segment,
                        _round(s.baseline),
                        _round(s.current),
                        _round(s.change),
                        s.pct,
                        share,
                        size,
                        gap,
                    ]
                )
            gaps = [r[8] for r in rows if isinstance(r[8], float)]
            dimensions.append((max(gaps, default=-math.inf), rows[: self.top]))
        dimensions.sort(key=lambda d: d[0], reverse=True)
        rows = [row for _, dim_rows in dimensions for row in dim_rows]

        summary: dict[str, JsonScalar] = {
            "baseline_period": self.baseline.label(),
            "current_period": self.current.label(),
            "change": _round(total_change),
            "pct_change": _pct(base_total, total_change),
        }
        lead = max(dimensions[0][1], key=lambda r: r[8] if isinstance(r[8], float) else -math.inf)
        if isinstance(lead[8], float):
            summary["largest_gap"] = f"{lead[0]} = {lead[1]}"
            summary["largest_gap_share_of_change"] = lead[6]
        summary["baseline_total"] = _round(base_total)
        summary["current_total"] = _round(cur_total)
        summary["columns_compared"] = len(usable)

        names_shown = ", ".join(schema.label(n) for n in usable)
        columns = ["baseline", "current", "change", "pct_change", "share_of_change"]
        return OperationResult(
            operation=self.operation,
            description=(
                f"{compiler.metric_label(self.metric)}: {self.baseline.label()} vs "
                f"{self.current.label()}, change by {names_shown}"
                f"{_filter_note(schema, self.filters)}"
            ),
            table=TableResult(
                columns=[
                    ResultColumn(name="dimension", type="VARCHAR"),
                    ResultColumn(name="segment", type="VARCHAR"),
                ]
                + [
                    ResultColumn(name=c, type="DOUBLE")
                    for c in [*columns, "baseline_share", "share_gap"]
                ],
                rows=rows,
                row_count=len(rows),
                truncated=False,
            ),
            summary=summary,
            notes=notes,
        )


def _as_float(value: Any, agg: str) -> float | None:
    if value is None:
        # No rows in the period: zero for additive metrics, unknown otherwise.
        return 0.0 if agg in _ADDITIVE_AGGS else None
    return float(value)


def _pct(base: float | None, change: float | None) -> float | None:
    if base is None or change is None or base == 0:
        return None
    return _ratio(change / abs(base))


class DistributionOp(BaseModel):
    """Histogram and summary statistics of one numeric column."""

    model_config = ConfigDict(extra="forbid")

    operation: Literal["distribution"] = "distribution"
    column: str
    bins: int = Field(default=20, ge=2, le=50)
    filters: list[Filter] = Field(default_factory=list, max_length=10)

    def run(self, engine: QueryEngine, schema: DatasetSchema) -> OperationResult:
        compiler = _Compiler(schema)
        col = quote(schema.get(self.column, allowed={"numeric"}, role="distribution column").name)
        clauses, params = compiler.filters(self.filters)
        clauses.insert(0, f"{col} IS NOT NULL")
        stats_sql = (
            f"SELECT COUNT(*), MIN({col}), MAX({col}), AVG({col}), MEDIAN({col}), "
            f"STDDEV_SAMP({col}), QUANTILE_CONT({col}, 0.25), QUANTILE_CONT({col}, 0.75) "
            f"FROM {TABLE_NAME}{_where(clauses)}"
        )
        count, low, high, mean, median, std, q1, q3 = engine.execute(stats_sql, params).rows[0]
        summary: dict[str, JsonScalar] = {
            "count": count,
            "min": low,
            "max": high,
            "mean": _round(_num(mean)),
            "median": _round(_num(median)),
            "std": _round(_num(std)),
            "q1": _round(_num(q1)),
            "q3": _round(_num(q3)),
        }
        rows: list[list[JsonScalar]] = []
        if count and low is not None and high is not None:
            lo, hi = float(low), float(high)
            bins = self.bins if hi > lo else 1
            width = (hi - lo) / bins if hi > lo else 1.0
            bucket_sql = (
                f"SELECT LEAST(CAST(FLOOR((CAST({col} AS DOUBLE) - ?) / ?) AS INTEGER), ?) AS b, "
                f"COUNT(*) FROM {TABLE_NAME}{_where(clauses)} GROUP BY b ORDER BY b"
            )
            counts = {
                int(b): int(n)
                for b, n in engine.execute(bucket_sql, [lo, width, bins - 1, *params]).rows
                if b is not None and n is not None
            }
            for i in range(bins):
                start = lo + i * width
                end = hi if i == bins - 1 else lo + (i + 1) * width
                rows.append([_round(start), _round(end), counts.get(i, 0)])
        table = TableResult(
            columns=[
                ResultColumn(name="bin_start", type="DOUBLE"),
                ResultColumn(name="bin_end", type="DOUBLE"),
                ResultColumn(name="count", type="BIGINT"),
            ],
            rows=rows,
            row_count=len(rows),
            truncated=False,
        )
        return OperationResult(
            operation=self.operation,
            description=(
                f"Distribution of {schema.label(self.column)}{_filter_note(schema, self.filters)}"
            ),
            table=table,
            summary=summary,
        )


def _num(value: Any) -> float | None:
    return None if value is None else float(value)


class CorrelationOp(BaseModel):
    """Pairwise correlation between numeric columns (rows with any missing value are dropped)."""

    model_config = ConfigDict(extra="forbid")

    operation: Literal["correlation"] = "correlation"
    columns: list[str] = Field(min_length=2, max_length=10)
    method: Literal["pearson", "spearman"] = "pearson"
    filters: list[Filter] = Field(default_factory=list, max_length=10)

    def run(self, engine: QueryEngine, schema: DatasetSchema) -> OperationResult:
        compiler = _Compiler(schema)
        if len(set(self.columns)) != len(self.columns):
            raise OperationError("Correlation columns must be distinct.")
        cols = [
            quote(schema.get(c, allowed={"numeric"}, role="correlation column").name)
            for c in self.columns
        ]
        clauses, params = compiler.filters(self.filters)
        clauses += [f"{c} IS NOT NULL" for c in cols]
        if self.method == "spearman":
            # Average rank for ties: rank + (tie count - 1) / 2.
            ranked = ", ".join(
                f"RANK() OVER (ORDER BY {c}) + (COUNT(*) OVER (PARTITION BY {c}) - 1) / 2.0 AS r{i}"
                for i, c in enumerate(cols)
            )
            source = f"(SELECT {ranked} FROM {TABLE_NAME}{_where(clauses)})"
            refs = [f"r{i}" for i in range(len(cols))]
            where = ""
        else:
            source = TABLE_NAME
            refs = cols
            where = _where(clauses)
        pairs = [(i, j) for i in range(len(cols)) for j in range(i + 1, len(cols))]
        selects = ["COUNT(*)"] + [f"CORR({refs[i]}, {refs[j]})" for i, j in pairs]
        values = engine.execute(f"SELECT {', '.join(selects)} FROM {source}{where}", params).rows[0]
        n = values[0]
        matrix: dict[tuple[int, int], float | None] = {}
        for (i, j), value in zip(pairs, values[1:], strict=True):
            matrix[(i, j)] = matrix[(j, i)] = _ratio(_num(value))
        rows: list[list[JsonScalar]] = []
        for i, a in enumerate(self.columns):
            for j, b in enumerate(self.columns):
                rows.append([a, b, 1.0 if i == j else matrix[(i, j)], n])
        table = TableResult(
            columns=[
                ResultColumn(name="column_a", type="VARCHAR"),
                ResultColumn(name="column_b", type="VARCHAR"),
                ResultColumn(name="correlation", type="DOUBLE"),
                ResultColumn(name="n", type="BIGINT"),
            ],
            rows=rows,
            row_count=len(rows),
            truncated=False,
        )
        labels = ", ".join(schema.label(c) for c in self.columns)
        return OperationResult(
            operation=self.operation,
            description=(
                f"{self.method.title()} correlation of {labels}{_filter_note(schema, self.filters)}"
            ),
            table=table,
            summary={"n": n, "method": self.method},
            notes=["Correlation measures association, not causation."],
        )


class OutliersOp(BaseModel):
    """Find unusually high or low values of a numeric column (IQR or z-score rule)."""

    model_config = ConfigDict(extra="forbid")

    operation: Literal["outliers"] = "outliers"
    column: str
    method: Literal["iqr", "zscore"] = "iqr"
    threshold: float | None = Field(
        default=None, gt=0, le=10, description="IQR multiplier (default 1.5) or z (default 3)."
    )
    include_columns: list[str] = Field(
        default_factory=list, max_length=8, description="Extra columns to show for context."
    )
    filters: list[Filter] = Field(default_factory=list, max_length=10)
    limit: int = Field(default=20, ge=1, le=100)

    def run(self, engine: QueryEngine, schema: DatasetSchema) -> OperationResult:
        compiler = _Compiler(schema)
        col = quote(schema.get(self.column, allowed={"numeric"}, role="outlier column").name)
        context = [quote(schema.get(c).name) for c in self.include_columns if c != self.column]
        clauses, params = compiler.filters(self.filters)
        clauses.insert(0, f"{col} IS NOT NULL")
        stats = engine.execute(
            f"SELECT COUNT(*), QUANTILE_CONT({col}, 0.25), QUANTILE_CONT({col}, 0.75), "
            f"AVG({col}), STDDEV_SAMP({col}), MEDIAN({col}) FROM {TABLE_NAME}{_where(clauses)}",
            params,
        ).rows[0]
        count, q1, q3, mean, std, median = (_num(v) for v in stats)
        if not count:
            raise OperationError(f"'{self.column}' has no values to check.")
        if self.method == "iqr":
            k = self.threshold or 1.5
            spread = (q3 or 0) - (q1 or 0)
            lower, upper, center = (q1 or 0) - k * spread, (q3 or 0) + k * spread, median or 0
        else:
            k = self.threshold or 3.0
            sd = std or 0.0
            lower, upper, center = (mean or 0) - k * sd, (mean or 0) + k * sd, mean or 0
        outlier_clause = f"({col} < ? OR {col} > ?)"
        count_row = engine.execute(
            f"SELECT COUNT(*), MIN({col}), MAX({col}) FROM {TABLE_NAME}"
            f"{_where([*clauses, outlier_clause])}",
            [*params, lower, upper],
        ).rows[0]
        outlier_count = int(count_row[0] or 0)
        rows = engine.execute(
            f"SELECT {', '.join([*context, col])} FROM {TABLE_NAME}"
            f"{_where([*clauses, outlier_clause])} ORDER BY ABS({col} - ?) DESC LIMIT {self.limit}",
            [*params, lower, upper, center],
        )
        notes = []
        if outlier_count > rows.row_count:
            # The rows are the most extreme ones, so their range is not the outliers' range.
            rows = rows.model_copy(update={"truncated": True})
            notes.append(
                f"Showing the {rows.row_count} most extreme of {outlier_count} outliers; "
                "lowest_outlier and highest_outlier cover all of them."
            )
        return OperationResult(
            operation=self.operation,
            description=(
                f"Outliers in {schema.label(self.column)} ({self.method}, threshold {k:g})"
                f"{_filter_note(schema, self.filters)}"
            ),
            table=rows,
            summary={
                "method": self.method,
                "threshold": k,
                "lower_bound": _round(lower),
                "upper_bound": _round(upper),
                "outlier_count": outlier_count,
                "outlier_share": _ratio(outlier_count / count),
                "lowest_outlier": _num(count_row[1]),
                "highest_outlier": _num(count_row[2]),
                "checked_values": int(count),
            },
            notes=notes,
        )


class MissingValuesOp(BaseModel):
    """Count missing values per column."""

    model_config = ConfigDict(extra="forbid")

    operation: Literal["missing_values"] = "missing_values"
    columns: list[str] = Field(default_factory=list, description="Defaults to all columns.")

    def run(self, engine: QueryEngine, schema: DatasetSchema) -> OperationResult:
        names = self.columns or [c.name for c in schema.columns]
        cols = [schema.get(n).name for n in names]
        selects = ["COUNT(*)"] + [f"COUNT(*) - COUNT({quote(c)})" for c in cols]
        values = engine.execute(f"SELECT {', '.join(selects)} FROM {TABLE_NAME}").rows[0]
        total = int(values[0] or 0)
        rows: list[list[JsonScalar]] = [
            [c, int(m or 0), _ratio(int(m or 0) / total) if total else 0.0]
            for c, m in zip(cols, values[1:], strict=True)
        ]
        rows.sort(key=lambda r: r[1] if isinstance(r[1], int) else 0, reverse=True)
        return OperationResult(
            operation=self.operation,
            description="Missing values per column",
            table=TableResult(
                columns=[
                    ResultColumn(name="column", type="VARCHAR"),
                    ResultColumn(name="missing_count", type="BIGINT"),
                    ResultColumn(name="missing_share", type="DOUBLE"),
                ],
                rows=rows,
                row_count=len(rows),
                truncated=False,
            ),
            summary={"row_count": total},
        )


class RowsOp(BaseModel):
    """Return individual rows matching filters (for 'show me the orders where ...')."""

    model_config = ConfigDict(extra="forbid")

    operation: Literal["rows"] = "rows"
    columns: list[str] = Field(default_factory=list, max_length=20, description="Defaults to all.")
    filters: list[Filter] = Field(default_factory=list, max_length=10)
    sort_by: str | None = None
    descending: bool = True
    limit: int = Field(default=20, ge=1, le=200)

    def run(self, engine: QueryEngine, schema: DatasetSchema) -> OperationResult:
        compiler = _Compiler(schema)
        names = self.columns or [c.name for c in schema.columns]
        cols = [quote(schema.get(n).name) for n in names]
        clauses, params = compiler.filters(self.filters)
        order = ""
        if self.sort_by:
            sort = quote(schema.get(self.sort_by, role="sort column").name)
            order = f" ORDER BY {sort} {'DESC' if self.descending else 'ASC'} NULLS LAST"
        select = f"SELECT {', '.join(cols)} FROM {TABLE_NAME}{_where(clauses)}"
        table = engine.execute(f"{select}{order} LIMIT {self.limit}", params)
        matching = engine.execute(
            f"SELECT COUNT(*) FROM {TABLE_NAME}{_where(clauses)}", params
        ).rows[0][0]
        return OperationResult(
            operation=self.operation,
            description=f"Rows{_filter_note(schema, self.filters)}",
            table=table,
            summary={"matching_rows": matching, "rows_shown": table.row_count},
        )


AnalysisOperation = Annotated[
    AggregateOp
    | TimeSeriesOp
    | PeriodComparisonOp
    | ChangeDriversOp
    | DistributionOp
    | CorrelationOp
    | OutliersOp
    | MissingValuesOp
    | RowsOp,
    Field(discriminator="operation"),
]


def run_operation(
    operation: AnalysisOperation, engine: QueryEngine, schema: DatasetSchema
) -> OperationResult:
    return operation.run(engine, schema)
