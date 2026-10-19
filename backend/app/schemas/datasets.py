from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.datasets.inference import SemanticType
from app.datasets.profiling import DatasetProfile
from app.jsonsafe import JsonScalar


class ColumnInfo(BaseModel):
    name: str
    original_name: str
    semantic_type: SemanticType
    dtype: str


class DatasetSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    original_filename: str
    file_format: Literal["csv", "xlsx"]
    sheet_name: str | None
    upload_size_bytes: int
    row_count: int
    column_count: int
    created_at: datetime


class DatasetDetail(DatasetSummary):
    columns: list[ColumnInfo]
    profile: DatasetProfile


class DatasetList(BaseModel):
    items: list[DatasetSummary]
    total: int
    limit: int
    offset: int


class DatasetPreview(BaseModel):
    columns: list[str]
    rows: list[list[JsonScalar]]
    offset: int
    limit: int
    total_rows: int
