"""Dataset profile: per-column statistics and data-quality warnings, computed once at upload."""

from __future__ import annotations

import math
from typing import Any, Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel

from app.datasets.inference import ColumnNote, ColumnSchema, SemanticType

_TOP_VALUES = 10
_HISTOGRAM_BINS = 20
HIGH_MISSING_SHARE = 0.5


class NumericStats(BaseModel):
    min: float | None
    max: float | None
    mean: float | None
    median: float | None
    std: float | None
    q1: float | None
    q3: float | None
    sum: float | None
    zeros: int
    negatives: int


class HistogramBin(BaseModel):
    start: float
    end: float
    count: int


class ValueCount(BaseModel):
    value: str
    count: int


class DatetimeStats(BaseModel):
    min: str | None
    max: str | None
    span_days: float | None


class TextStats(BaseModel):
    min_length: int
    max_length: int
    mean_length: float


class ColumnProfile(BaseModel):
    name: str
    original_name: str
    semantic_type: SemanticType
    dtype: str
    non_null_count: int
    missing_count: int
    missing_share: float
    unique_count: int
    numeric: NumericStats | None = None
    histogram: list[HistogramBin] | None = None
    datetime: DatetimeStats | None = None
    text: TextStats | None = None
    top_values: list[ValueCount] | None = None


class DataQualityWarning(BaseModel):
    code: str
    severity: Literal["info", "warning"]
    message: str
    column: str | None = None


class DatasetProfile(BaseModel):
    row_count: int
    column_count: int
    duplicate_row_count: int
    missing_cell_count: int
    columns: list[ColumnProfile]
    warnings: list[DataQualityWarning]


def _finite(value: Any) -> float | None:
    if value is None or value is pd.NA:
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _numeric_stats(values: pd.Series) -> tuple[NumericStats, list[HistogramBin]]:
    numbers = values.dropna().astype("float64")
    stats = NumericStats(
        min=_finite(numbers.min()),
        max=_finite(numbers.max()),
        mean=_finite(numbers.mean()),
        median=_finite(numbers.median()),
        std=_finite(numbers.std()) if len(numbers) > 1 else None,
        q1=_finite(numbers.quantile(0.25)),
        q3=_finite(numbers.quantile(0.75)),
        sum=_finite(numbers.sum()),
        zeros=int((numbers == 0).sum()),
        negatives=int((numbers < 0).sum()),
    )
    counts, edges = np.histogram(numbers.to_numpy(), bins=_HISTOGRAM_BINS)
    histogram = [
        HistogramBin(start=float(edges[i]), end=float(edges[i + 1]), count=int(counts[i]))
        for i in range(len(counts))
    ]
    return stats, histogram


def _top_values(values: pd.Series) -> list[ValueCount]:
    counts = values.dropna().astype(str).value_counts().head(_TOP_VALUES)
    return [ValueCount(value=str(v), count=int(c)) for v, c in counts.items()]


def _column_profile(series: pd.Series, schema: ColumnSchema) -> ColumnProfile:
    total = len(series)
    missing = int(series.isna().sum())
    present = series.dropna()
    profile = ColumnProfile(
        name=schema.name,
        original_name=schema.original_name,
        semantic_type=schema.semantic_type,
        dtype=schema.dtype,
        non_null_count=total - missing,
        missing_count=missing,
        missing_share=round(missing / total, 6) if total else 0.0,
        unique_count=int(present.nunique()),
    )
    if present.empty:
        return profile
    if schema.semantic_type == "numeric":
        profile.numeric, profile.histogram = _numeric_stats(series)
    elif schema.semantic_type == "datetime":
        start, end = present.min(), present.max()
        profile.datetime = DatetimeStats(
            min=start.isoformat(),
            max=end.isoformat(),
            span_days=round((end - start).total_seconds() / 86_400, 3),
        )
    else:
        profile.top_values = _top_values(series)
        if schema.semantic_type in ("categorical", "text"):
            lengths = present.astype(str).str.len()
            profile.text = TextStats(
                min_length=int(lengths.min()),
                max_length=int(lengths.max()),
                mean_length=round(float(lengths.mean()), 2),
            )
    return profile


def _quality_warnings(
    profiles: list[ColumnProfile], duplicate_rows: int, row_count: int
) -> list[DataQualityWarning]:
    warnings: list[DataQualityWarning] = []
    if duplicate_rows:
        warnings.append(
            DataQualityWarning(
                code="duplicate_rows",
                severity="warning",
                message=f"{duplicate_rows:,} row(s) are exact duplicates of another row.",
            )
        )
    for column in profiles:
        if 0 < column.missing_count < row_count and column.missing_share >= HIGH_MISSING_SHARE:
            warnings.append(
                DataQualityWarning(
                    code="high_missing",
                    severity="warning",
                    message=f"{column.missing_share:.0%} of values are missing.",
                    column=column.name,
                )
            )
        if column.unique_count == 1 and row_count > 1:
            warnings.append(
                DataQualityWarning(
                    code="constant",
                    severity="info",
                    message="Every value is the same, so this column can't explain differences.",
                    column=column.name,
                )
            )
        if (
            column.semantic_type in ("categorical", "text")
            and column.non_null_count > 20
            and column.unique_count == column.non_null_count
        ):
            warnings.append(
                DataQualityWarning(
                    code="possible_identifier",
                    severity="info",
                    message="Every value is unique; this looks like an identifier.",
                    column=column.name,
                )
            )
        if column.numeric and column.numeric.q1 is not None and column.numeric.q3 is not None:
            spread = column.numeric.q3 - column.numeric.q1
            low, high = column.numeric.q1 - 3 * spread, column.numeric.q3 + 3 * spread
            if spread > 0 and ((column.numeric.min or 0) < low or (column.numeric.max or 0) > high):
                warnings.append(
                    DataQualityWarning(
                        code="extreme_values",
                        severity="info",
                        message="Some values are far outside the typical range (more than "
                        "3 times the interquartile range).",
                        column=column.name,
                    )
                )
    return warnings


_NOTE_SEVERITY: dict[str, Literal["info", "warning"]] = {
    "all_missing": "warning",
    "unparsed_values": "warning",
    "mixed_types": "warning",
    "ambiguous_dates": "warning",
    "encoding_fallback": "warning",
}


def build_profile(
    frame: pd.DataFrame, columns: list[ColumnSchema], notes: list[ColumnNote]
) -> DatasetProfile:
    profiles = [_column_profile(frame[c.name], c) for c in columns]
    duplicate_rows = int(frame.duplicated().sum())
    warnings = [
        DataQualityWarning(
            code=note.code,
            severity=_NOTE_SEVERITY.get(note.code, "info"),
            message=note.message,
            column=note.column,
        )
        for note in notes
    ]
    warnings.extend(_quality_warnings(profiles, duplicate_rows, len(frame)))
    return DatasetProfile(
        row_count=len(frame),
        column_count=len(columns),
        duplicate_row_count=duplicate_rows,
        missing_cell_count=int(frame.isna().sum().sum()),
        columns=profiles,
        warnings=warnings,
    )
