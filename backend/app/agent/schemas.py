"""Data contracts of the analysis agent: plan, answer, activity events and stored results."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.analytics.charts import ChartSpec
from app.analytics.engine import TableResult
from app.jsonsafe import JsonScalar

# --- Model outputs (validated structured outputs) -------------------------------------------

Intent = Literal[
    "aggregation",
    "trend",
    "comparison",
    "ranking",
    "breakdown",
    "relationship",
    "outliers",
    "missing_data",
    "data_quality",
    "lookup",
    "other",
]


class PlannedStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(description="One short sentence: what to compute and why.")
    tool: Literal[
        "inspect_dataset", "get_dataset_profile", "execute_analysis", "execute_sql", "create_chart"
    ]


class AnalysisPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: Intent
    answerable: bool = Field(
        description="False when the dataset lacks the information needed to answer."
    )
    missing_information: str | None = Field(
        default=None, description="If not answerable: what data would be needed."
    )
    relevant_columns: list[str] = Field(description="Exact column names from the dataset.")
    interpretation: str | None = Field(
        default=None,
        description="How ambiguous terms were resolved, e.g. which year 'Q3' refers to.",
    )
    steps: list[PlannedStep] = Field(description="1 to 6 steps.")


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statement: str = Field(description="One sentence. Use numbers exactly as computed.")
    kind: Literal["fact", "hypothesis"] = Field(
        description="fact: directly shown by a computed result. hypothesis: a possible "
        "explanation the data does not prove."
    )
    evidence: list[str] = Field(description="Result ids (e.g. r2) that support the statement.")


class FinalAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(description="A direct answer to the question in 1 to 3 sentences.")
    findings: list[Finding] = Field(description="Up to 8 findings, most important first.")
    caveats: list[str] = Field(
        description="Limitations: data quality, missing information, assumptions."
    )
    chart_ids: list[str] = Field(description="Ids of created charts worth showing, e.g. c1.")
    follow_up_questions: list[str] = Field(description="Up to 3 useful next questions.")


# --- Runtime records -------------------------------------------------------------------------

EventStatus = Literal["running", "completed", "failed"]


class ActivityEvent(BaseModel):
    """A high-level, user-visible step. Labels describe operations that actually ran."""

    # Fields with defaults are always present in responses; say so in the schema.
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    kind: Literal["step", "tool"]
    # Stable identity of the step within a run; a later event with the same key updates it
    # (e.g. "running" -> "completed").
    key: str
    label: str
    status: EventStatus
    detail: str | None = None
    result_id: str | None = None


class StoredResult(BaseModel):
    # Fields with defaults are always present in responses; say so in the schema.
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: str
    tool: str
    operation: str
    description: str
    table: TableResult
    summary: dict[str, JsonScalar] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
    sql: str | None = None
    # The validated tool input that produced this result (how it was computed).
    arguments: dict[str, Any] | None = None


class GroundingReport(BaseModel):
    # Fields with defaults are always present in responses; say so in the schema.
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    checked_numbers: int = 0
    unverified_numbers: list[str] = Field(default_factory=list)
    invalid_references: list[str] = Field(default_factory=list)
    unsupported_facts: list[str] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not (self.unverified_numbers or self.invalid_references or self.unsupported_facts)


StopReason = Literal[
    "completed", "not_answerable", "iteration_limit", "tool_limit", "deadline", "cancelled", "error"
]


class AgentOutcome(BaseModel):
    """Everything a run produced. Persisted as the analysis result."""

    # Fields with defaults are always present in responses; say so in the schema.
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    status: Literal["completed", "failed", "cancelled"]
    stop_reason: StopReason
    plan: AnalysisPlan | None = None
    answer: FinalAnswer | None = None
    results: list[StoredResult] = Field(default_factory=list)
    charts: list[ChartSpec] = Field(default_factory=list)
    grounding: GroundingReport | None = None
    error_code: str | None = None
    error_message: str | None = None
    iterations: int = 0
    tool_calls: int = 0
    usage: dict[str, Any] = Field(default_factory=dict)
