"""The agent's tools: definitions shown to the model, input validation, and execution.

Only these five tools exist (the allowlist). Every input is validated with Pydantic before
anything runs; invalid input, rejected SQL or failed queries come back to the model as error
results it can correct. Every successful result is stored with an id (r1, r2, ...) so answers
and charts can reference it. Activity labels are generated from the validated input, not from
model-written text.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.agent.context import DatasetContext
from app.agent.llm.base import ToolCall, ToolOutcome, ToolSpec
from app.agent.schemas import ActivityEvent, StoredResult
from app.analytics.charts import ChartRequest, ChartSpec, build_chart
from app.analytics.engine import (
    AnalyticsEngine,
    AnalyticsError,
    ResultColumn,
    TableResult,
)
from app.analytics.operations import AnalysisOperation, DatasetSchema, RowsOp
from app.analytics.sql_guard import validate_sql
from app.jsonsafe import JsonScalar

logger = logging.getLogger(__name__)

MAX_ROWS_FOR_MODEL = 30
MAX_CELL_CHARS = 120


# --- Inputs ----------------------------------------------------------------------------------


class InspectDatasetInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample_rows: int = Field(default=5, ge=1, le=20, description="Number of rows to show.")
    columns: list[str] = Field(default_factory=list, description="Defaults to all columns.")


class GetProfileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    columns: list[str] = Field(min_length=1, max_length=20)


class ExecuteAnalysisInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis: AnalysisOperation


class ExecuteSQLInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sql: str = Field(max_length=5_000, description="One read-only SELECT over the table data.")
    purpose: str = Field(max_length=200, description="What the query computes, in a few words.")


TOOL_INPUTS: dict[str, type[BaseModel]] = {
    "inspect_dataset": InspectDatasetInput,
    "get_dataset_profile": GetProfileInput,
    "execute_analysis": ExecuteAnalysisInput,
    "execute_sql": ExecuteSQLInput,
    "create_chart": ChartRequest,
}

_DESCRIPTIONS = {
    "inspect_dataset": "Show a few raw rows of the dataset to see what values look like.",
    "get_dataset_profile": (
        "Return the stored profile (type, missing values, distinct count, statistics, top "
        "values) of specific columns."
    ),
    "execute_analysis": (
        "Run a typed analytical operation on the dataset: aggregate (group and summarise, "
        "rankings), time_series (metrics per day/week/month/quarter/year), period_comparison "
        "(compare two date ranges, optionally by segment, with each segment's contribution to "
        "the change), distribution (histogram and statistics), correlation, outliers, "
        "missing_values, or rows (individual matching rows). Prefer this over SQL."
    ),
    "execute_sql": (
        "Run one read-only SQL SELECT over the table `data` (DuckDB dialect) when no typed "
        "operation fits. Only allowlisted functions, no other tables, results capped."
    ),
    "create_chart": (
        "Create a chart from an existing result id. Choose the chart type and which result "
        "columns go on each axis; the data is taken from that result."
    ),
}


def tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(name=name, description=_DESCRIPTIONS[name], input_schema=model.model_json_schema())
        for name, model in TOOL_INPUTS.items()
    ]


# --- Execution -------------------------------------------------------------------------------


@dataclass
class ToolExecution:
    outcome: ToolOutcome
    event: ActivityEvent


def _clip(value: JsonScalar) -> JsonScalar:
    if isinstance(value, str) and len(value) > MAX_CELL_CHARS:
        return value[: MAX_CELL_CHARS - 1] + "…"
    return value


def observation(result: StoredResult) -> str:
    """The compact JSON the model sees for a result."""
    rows = [[_clip(v) for v in row] for row in result.table.rows[:MAX_ROWS_FOR_MODEL]]
    payload: dict[str, Any] = {
        "result_id": result.id,
        "description": result.description,
        "columns": [c.name for c in result.table.columns],
        "rows": rows,
        "rows_shown": len(rows),
        "row_count": result.table.row_count,
        "truncated_by_engine": result.table.truncated,
    }
    if result.summary:
        payload["summary"] = result.summary
    if result.notes:
        payload["notes"] = result.notes
    return json.dumps(payload, default=str)


class ToolExecutor:
    def __init__(
        self,
        *,
        engine: AnalyticsEngine,
        context: DatasetContext,
        profile: dict[str, Any],
    ) -> None:
        self.engine = engine
        self.context = context
        self.schema: DatasetSchema = context.schema()
        self._profile_columns = {c["name"]: c for c in profile.get("columns", [])}
        self.results: dict[str, StoredResult] = {}
        self.charts: dict[str, ChartSpec] = {}

    def _next_result_id(self) -> str:
        return f"r{len(self.results) + 1}"

    def execute(self, call: ToolCall) -> ToolExecution:
        model = TOOL_INPUTS.get(call.name)
        if model is None:
            return self._failure(call, "Unknown tool", f"There is no tool named {call.name!r}.")
        try:
            arguments = model.model_validate(call.input)
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(str(p) for p in error['loc']) or 'input'}: {error['msg']}"
                for error in exc.errors()[:8]
            )
            return self._failure(call, "Invalid tool input", f"Invalid input: {problems}")
        try:
            if isinstance(arguments, InspectDatasetInput):
                return self._inspect(call, arguments)
            if isinstance(arguments, GetProfileInput):
                return self._profile(call, arguments)
            if isinstance(arguments, ExecuteAnalysisInput):
                return self._analysis(call, arguments)
            if isinstance(arguments, ExecuteSQLInput):
                return self._sql(call, arguments)
            assert isinstance(arguments, ChartRequest)
            return self._chart(call, arguments)
        except AnalyticsError as exc:
            return self._failure(call, _failure_label(call.name), exc.message)

    def _failure(self, call: ToolCall, label: str, message: str) -> ToolExecution:
        return ToolExecution(
            outcome=ToolOutcome(call.id, f"Error: {message}", is_error=True),
            event=ActivityEvent(
                kind="tool", key=f"call:{call.id}", label=label, status="failed", detail=message
            ),
        )

    def _store(self, call: ToolCall, result: StoredResult, label: str) -> ToolExecution:
        self.results[result.id] = result
        detail = f"{result.table.row_count:,} row(s)"
        if result.table.truncated:
            detail += ", truncated"
        return ToolExecution(
            outcome=ToolOutcome(call.id, observation(result)),
            event=ActivityEvent(
                kind="tool",
                key=f"call:{call.id}",
                label=label,
                status="completed",
                detail=detail,
                result_id=result.id,
            ),
        )

    def _inspect(self, call: ToolCall, args: InspectDatasetInput) -> ToolExecution:
        rows = RowsOp(columns=args.columns, limit=args.sample_rows).run(self.engine, self.schema)
        table = rows.table
        result = StoredResult(
            id=self._next_result_id(),
            tool=call.name,
            operation="sample_rows",
            description=f"First {args.sample_rows} rows",
            table=table,
        )
        return self._store(call, result, "Reading sample rows")

    def _profile(self, call: ToolCall, args: GetProfileInput) -> ToolExecution:
        rows: list[list[JsonScalar]] = []
        for name in args.columns:
            column = self.schema.get(name)
            stats = self._profile_columns.get(column.name, {})
            numeric = stats.get("numeric") or {}
            dates = stats.get("datetime") or {}
            top = stats.get("top_values") or []
            rows.append(
                [
                    column.name,
                    column.semantic_type,
                    stats.get("missing_count"),
                    stats.get("unique_count"),
                    numeric.get("min", dates.get("min")),
                    numeric.get("max", dates.get("max")),
                    numeric.get("mean"),
                    numeric.get("median"),
                    "; ".join(f"{t['value']} ({t['count']})" for t in top[:8]) or None,
                ]
            )
        names = ["column", "type", "missing", "distinct", "min", "max", "mean", "median", "top"]
        table = TableResult(
            columns=[ResultColumn(name=n, type="VARCHAR") for n in names],
            rows=rows,
            row_count=len(rows),
            truncated=False,
        )
        labels = ", ".join(self.schema.label(n) for n in args.columns[:4])
        result = StoredResult(
            id=self._next_result_id(),
            tool=call.name,
            operation="profile",
            description=f"Profile of {labels}",
            table=table,
        )
        return self._store(call, result, f"Reviewing column profiles: {labels}")

    def _analysis(self, call: ToolCall, args: ExecuteAnalysisInput) -> ToolExecution:
        operation = args.analysis
        outcome = operation.run(self.engine, self.schema)
        result = StoredResult(
            id=self._next_result_id(),
            tool=call.name,
            operation=outcome.operation,
            description=outcome.description,
            table=outcome.table,
            summary=outcome.summary,
            notes=outcome.notes,
        )
        return self._store(call, result, _analysis_label(outcome.operation, outcome.description))

    def _sql(self, call: ToolCall, args: ExecuteSQLInput) -> ToolExecution:
        sql = validate_sql(args.sql)
        table = self.engine.execute(sql)
        result = StoredResult(
            id=self._next_result_id(),
            tool=call.name,
            operation="sql",
            description=f"SQL query: {args.purpose.strip()[:120] or 'custom query'}",
            table=table,
            sql=sql,
        )
        execution = self._store(call, result, "Running a validated SQL query")
        execution.event.detail = f"{sql[:160]}{'…' if len(sql) > 160 else ''}"
        return execution

    def _chart(self, call: ToolCall, args: ChartRequest) -> ToolExecution:
        source = self.results.get(args.result_id)
        if source is None:
            known = ", ".join(self.results) or "none yet"
            raise AnalyticsError(
                f"Result {args.result_id} does not exist in this analysis (results: {known}).",
                code="invalid_chart",
            )
        chart_id = f"c{len(self.charts) + 1}"
        spec = build_chart(args, source.table, chart_id)
        self.charts[chart_id] = spec
        return ToolExecution(
            outcome=ToolOutcome(
                call.id,
                json.dumps(
                    {
                        "chart_id": chart_id,
                        "chart_type": spec.chart_type,
                        "title": spec.title,
                        "source_result_id": spec.source_result_id,
                        "series": [t.name for t in spec.traces],
                        "notes": spec.notes,
                    }
                ),
            ),
            event=ActivityEvent(
                kind="tool",
                key=f"call:{call.id}",
                label=f"Generating chart: {spec.title}",
                status="completed",
                detail=f"{spec.chart_type.replace('_', ' ')} from {spec.source_result_id}",
            ),
        )


_OPERATION_VERBS = {
    "aggregate": "Computing",
    "time_series": "Building time series:",
    "period_comparison": "Comparing periods:",
    "distribution": "Measuring",
    "correlation": "Measuring",
    "outliers": "Looking for",
    "missing_values": "Counting",
    "rows": "Retrieving",
}


def _analysis_label(operation: str, description: str) -> str:
    verb = _OPERATION_VERBS.get(operation, "Running")
    text = description[0].lower() + description[1:] if description else operation
    if operation in {"aggregate", "time_series", "period_comparison"}:
        text = description
    return f"{verb} {text}"[:200]


def _failure_label(tool: str) -> str:
    return {
        "execute_sql": "SQL query rejected or failed",
        "execute_analysis": "Analysis step failed",
        "create_chart": "Chart could not be created",
    }.get(tool, "Tool failed")
