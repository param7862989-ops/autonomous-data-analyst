from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agent.schemas import AgentOutcome

RunStatus = Literal["queued", "running", "completed", "failed", "cancelled"]


class ConversationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: uuid.UUID
    title: str | None = Field(default=None, max_length=200)


class ConversationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)


class ConversationSummary(BaseModel):
    id: uuid.UUID
    dataset_id: uuid.UUID
    dataset_name: str
    title: str
    run_count: int
    created_at: datetime
    updated_at: datetime


class ConversationList(BaseModel):
    items: list[ConversationSummary]
    total: int
    limit: int
    offset: int


class AnalysisCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=2_000)


class RunSummary(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    dataset_id: uuid.UUID
    question: str
    status: RunStatus
    stop_reason: str | None
    answer_summary: str | None
    created_at: datetime
    finished_at: datetime | None


class ConversationDetail(ConversationSummary):
    runs: list[RunSummary]


class RunList(BaseModel):
    items: list[RunSummary]
    total: int
    limit: int
    offset: int


class HistoryItem(RunSummary):
    dataset_name: str


class HistoryList(BaseModel):
    items: list[HistoryItem]
    total: int
    limit: int
    offset: int


class ActivityEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    seq: int
    kind: Literal["step", "tool"]
    label: str
    status: Literal["running", "completed", "failed"]
    detail: str | None
    result_id: str | None
    updated_at: datetime


class RunDetail(RunSummary):
    error_code: str | None
    error_message: str | None
    model: str | None
    cancel_requested: bool
    started_at: datetime | None
    events: list[ActivityEventOut]
    outcome: AgentOutcome | None


class ServerConfig(BaseModel):
    # Fields with defaults are always present in responses; say so in the schema.
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    analysis_enabled: bool
    model: str | None
    max_question_length: int = 2_000
