"""Column-name normalization and column type inference.

Column names become unique snake_case identifiers (the original text is kept for display), which
makes SQL generated over the dataset simpler and less error-prone. Each column is assigned one
semantic type — numeric, datetime, boolean, categorical or text — from its values.
"""

from __future__ import annotations

import datetime as dt
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
import pandas as pd

SemanticType = Literal["numeric", "datetime", "boolean", "categorical", "text"]

# Cell text treated as "no value" (compared case-insensitively after trimming).
MISSING_TOKENS = frozenset(
    {
        "",
        "na",
        "n/a",
        "nan",
        "null",
        "none",
        "-",
        "--",
        "?",
        "#n/a",
        "#div/0!",
        "#value!",
        "#ref!",
        "#name?",
        "#num!",
        "#null!",
    }
)
_TRUE_TOKENS = frozenset({"true", "yes", "y", "t"})
_FALSE_TOKENS = frozenset({"false", "no", "n", "f"})

# A type is chosen when at least this share of non-missing values fits it.
TYPE_THRESHOLD = 0.95
# Below the threshold but above this share, the column is flagged as having mixed types.
MIXED_THRESHOLD = 0.5
_MAX_NAME_LENGTH = 63
_DATE_SAMPLE = 2_000

_DATE_LIKE = re.compile(
    r"^(\d{4}[-/.]\d{1,2}([-/.]\d{1,2})?|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4})"
    r"([ T]\d{1,2}:\d{2}(:\d{2}(\.\d+)?)?)?\s*(Z|[+-]\d{2}:?\d{2})?$"
    r"|^[A-Za-z]{3,9}\.? \d{1,2},? \d{4}$"
    r"|^\d{1,2} [A-Za-z]{3,9}\.? \d{4}$"
)
_DATE_FORMATS = (
    "ISO8601",
    "%m/%d/%Y",
    "%d/%m/%Y",
    "%m/%d/%Y %H:%M",
    "%d/%m/%Y %H:%M",
    "%m/%d/%y",
    "%d/%m/%y",
    "%Y/%m/%d",
    "%d-%m-%Y",
    "%d.%m.%Y",
    "%b %d, %Y",
    "%B %d, %Y",
    "%d %b %Y",
    "%d %B %Y",
)
_AMBIGUOUS_PAIRS = {
    "%m/%d/%Y": "%d/%m/%Y",
    "%m/%d/%Y %H:%M": "%d/%m/%Y %H:%M",
    "%m/%d/%y": "%d/%m/%y",
}


@dataclass
class ColumnNote:
    code: str
    message: str
    column: str | None = None


@dataclass
class ColumnSchema:
    name: str
    original_name: str
    semantic_type: SemanticType
    dtype: str


@dataclass
class TypedTable:
    frame: pd.DataFrame
    columns: list[ColumnSchema]
    notes: list[ColumnNote] = field(default_factory=list)


# --- Column names ----------------------------------------------------------------------------


def _snake_case(raw: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode()
    return re.sub(r"[^0-9a-zA-Z]+", "_", ascii_text).strip("_").lower()


def normalize_headers(headers: list[str]) -> tuple[list[str], list[ColumnNote]]:
    """Unique snake_case names. Empty or duplicate headers are renamed and reported."""
    names: list[str] = []
    notes: list[ColumnNote] = []
    seen: set[str] = set()
    for index, raw in enumerate(headers):
        text = raw.strip()
        base = _snake_case(text)[:_MAX_NAME_LENGTH] if text else ""
        if not base:
            base = f"column_{index + 1}"
            notes.append(
                ColumnNote(
                    "empty_header",
                    f"Column {index + 1} has no name; it is called {base}.",
                    base,
                )
            )
        elif base[0].isdigit():
            base = f"c_{base}"[:_MAX_NAME_LENGTH]
        name = base
        suffix = 2
        while name in seen:
            name = f"{base[: _MAX_NAME_LENGTH - len(str(suffix)) - 1]}_{suffix}"
            suffix += 1
        if name != base:
            notes.append(
                ColumnNote(
                    "duplicate_header",
                    f'The column name "{text}" appears more than once; this copy is called {name}.',
                    name,
                )
            )
        seen.add(name)
        names.append(name)
    return names, notes


# --- Cell cleanup ----------------------------------------------------------------------------


def _clean_cell(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and np.isnan(value):
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return None if stripped.lower() in MISSING_TOKENS else stripped
    return value


def clean_cells(series: pd.Series) -> pd.Series:
    """Object series with trimmed strings and ``None`` for every kind of missing value."""
    return series.astype(object).map(_clean_cell)


# --- Type detection --------------------------------------------------------------------------


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float | np.integer | np.floating) and not isinstance(
        value, bool | np.bool_
    )


def _parse_numeric_strings(strings: pd.Series) -> tuple[pd.Series, bool]:
    """Parse numeric text: thousands separators, currency symbols, (negatives), trailing %.

    Returns floats (NaN where unparseable) and whether any value had a percent sign.
    """
    text = strings.astype("str")
    parenthesised = text.str.match(r"^\(.*\)$")
    text = text.where(~parenthesised, "-" + text.str.slice(1, -1))
    text = text.str.replace(r"^([-+]?)\s*[$€£₹¥]\s*", r"\1", regex=True)
    text = text.str.replace(r"^[$€£₹¥]\s*([-+]?)", r"\1", regex=True)
    percent = text.str.endswith("%")
    text = text.where(~percent, text.str.slice(0, -1))
    thousands = text.str.match(r"^[-+]?\d{1,3}(,\d{3})+(\.\d+)?$")
    text = text.where(~thousands, text.str.replace(",", "", regex=False))
    numbers = pd.to_numeric(text, errors="coerce").astype("float64")
    numbers = numbers.where(np.isfinite(numbers))
    return numbers, bool(percent.any())


def _to_numeric(values: pd.Series) -> tuple[pd.Series, float, bool]:
    """Convert non-missing values to floats; return (numbers, share parsed, had_percent)."""
    number_mask = values.map(_is_number).astype(bool)
    result = pd.Series(np.nan, index=values.index, dtype="float64")
    result[number_mask] = values[number_mask].astype("float64")
    string_mask = values.map(lambda v: isinstance(v, str)).astype(bool)
    had_percent = False
    if string_mask.any():
        parsed, had_percent = _parse_numeric_strings(values[string_mask])
        result[string_mask] = parsed
    result = result.where(np.isfinite(result))
    share = float(result.notna().sum()) / max(len(values), 1)
    return result, share, had_percent


def _has_leading_zero_codes(values: pd.Series) -> bool:
    strings = values[values.map(lambda v: isinstance(v, str)).astype(bool)].astype("str")
    if strings.empty:
        return False
    return float(strings.str.match(r"^0\d+$").mean()) > 0.1


def _best_date_format(strings: pd.Series) -> tuple[str | None, float, bool]:
    sample = strings.iloc[:_DATE_SAMPLE].astype("str")
    if float(sample.str.match(_DATE_LIKE).mean()) < TYPE_THRESHOLD:
        return None, 0.0, False
    scores: dict[str, float] = {}
    for fmt in _DATE_FORMATS:
        parsed = pd.to_datetime(sample, format=fmt, errors="coerce", utc=True)
        scores[fmt] = float(parsed.notna().mean())
    best = max(scores, key=lambda f: scores[f])
    ambiguous = best in _AMBIGUOUS_PAIRS and scores[_AMBIGUOUS_PAIRS[best]] == scores[best]
    return best, scores[best], ambiguous


def _strings_to_datetime(strings: pd.Series, fmt: str) -> pd.Series:
    parsed = pd.to_datetime(strings.astype("str"), format=fmt, errors="coerce", utc=True)
    return parsed.dt.tz_convert(None)


def _to_datetime(values: pd.Series) -> tuple[pd.Series | None, float, list[ColumnNote]]:
    notes: list[ColumnNote] = []
    temporal_mask = values.map(lambda v: isinstance(v, dt.date | pd.Timestamp)).astype(bool)
    string_mask = values.map(lambda v: isinstance(v, str)).astype(bool)
    result = pd.Series(pd.NaT, index=values.index, dtype="datetime64[us]")
    if temporal_mask.any():
        converted = pd.to_datetime(values[temporal_mask], errors="coerce", utc=True)
        result[temporal_mask] = converted.dt.tz_convert(None).astype("datetime64[us]")
    if string_mask.any():
        fmt, score, ambiguous = _best_date_format(values[string_mask])
        if fmt is None or score < TYPE_THRESHOLD:
            if temporal_mask.sum() < TYPE_THRESHOLD * len(values):
                return None, 0.0, notes
        else:
            result[string_mask] = _strings_to_datetime(values[string_mask], fmt).astype(
                "datetime64[us]"
            )
            if ambiguous:
                notes.append(
                    ColumnNote(
                        "ambiguous_dates",
                        "Dates could be read as month/day or day/month; month/day was assumed.",
                    )
                )
    share = float(result.notna().sum()) / max(len(values), 1)
    return result, share, notes


def _to_boolean(values: pd.Series) -> pd.Series | None:
    def convert(value: Any) -> bool | None:
        if isinstance(value, bool | np.bool_):
            return bool(value)
        if isinstance(value, str):
            lowered = value.lower()
            if lowered in _TRUE_TOKENS:
                return True
            if lowered in _FALSE_TOKENS:
                return False
        raise ValueError

    try:
        return values.map(convert).astype("boolean")
    except ValueError:
        return None


def _numeric_dtype(numbers: pd.Series) -> pd.Series:
    finite = numbers.dropna()
    if (
        not finite.empty
        and bool((finite == np.floor(finite)).all())
        and (float(finite.abs().max()) < 2**53)
    ):
        return numbers.round().astype("Int64")
    return numbers


def _text_kind(values: pd.Series) -> SemanticType:
    unique = int(values.nunique())
    count = len(values)
    if unique <= 20 or (unique <= 1_000 and unique / max(count, 1) <= 0.5):
        return "categorical"
    return "text"


def infer_column(series: pd.Series, name: str) -> tuple[pd.Series, SemanticType, list[ColumnNote]]:
    """Return the converted column, its semantic type, and notes about the conversion."""
    cells = clean_cells(series)
    present = cells.dropna()
    notes: list[ColumnNote] = []

    if present.empty:
        notes.append(ColumnNote("all_missing", "Every value in this column is missing.", name))
        return pd.Series(pd.NA, index=cells.index, dtype="string"), "text", notes

    booleans = _to_boolean(present)
    if booleans is not None:
        full_booleans = pd.Series(pd.NA, index=cells.index, dtype="boolean")
        full_booleans[present.index] = booleans
        return full_booleans, "boolean", notes

    numbers, numeric_share, had_percent = _to_numeric(present)
    leading_zeros = _has_leading_zero_codes(present)
    if numeric_share >= TYPE_THRESHOLD and not leading_zeros:
        full = pd.Series(np.nan, index=cells.index, dtype="float64")
        full[present.index] = numbers
        unparsed = int(len(present) - numbers.notna().sum())
        if unparsed:
            notes.append(
                ColumnNote(
                    "unparsed_values",
                    f"{unparsed:,} value(s) weren't numbers and are treated as missing.",
                    name,
                )
            )
        if had_percent:
            notes.append(
                ColumnNote(
                    "percent_values",
                    "Values with a % sign were read as plain numbers (12% became 12).",
                    name,
                )
            )
        return _numeric_dtype(full), "numeric", notes

    dates, date_share, date_notes = _to_datetime(present)
    if dates is not None and date_share >= TYPE_THRESHOLD:
        full_dates = pd.Series(pd.NaT, index=cells.index, dtype="datetime64[us]")
        full_dates[present.index] = dates
        unparsed = int(len(present) - dates.notna().sum())
        if unparsed:
            notes.append(
                ColumnNote(
                    "unparsed_values",
                    f"{unparsed:,} value(s) weren't valid dates and are treated as missing.",
                    name,
                )
            )
        for note in date_notes:
            note.column = name
        return full_dates, "datetime", notes + date_notes

    if leading_zeros and numeric_share >= TYPE_THRESHOLD:
        notes.append(
            ColumnNote(
                "kept_as_text",
                "Values have leading zeros (like codes or IDs), so they were kept as text.",
                name,
            )
        )
    elif numeric_share >= MIXED_THRESHOLD:
        notes.append(
            ColumnNote(
                "mixed_types",
                f"{numeric_share:.0%} of values are numbers and the rest are text, so the "
                "column was kept as text.",
                name,
            )
        )

    # astype("string") maps both None and NaN to <NA>; never stringify a missing value.
    text = cells.astype("string")
    return text, _text_kind(present.map(str)), notes


def infer_table(headers: list[str], frame: pd.DataFrame) -> TypedTable:
    names, notes = normalize_headers(headers)
    converted: dict[str, pd.Series] = {}
    columns: list[ColumnSchema] = []
    for position, (name, original) in enumerate(zip(names, headers, strict=True)):
        series, semantic_type, column_notes = infer_column(frame.iloc[:, position], name)
        converted[name] = series.reset_index(drop=True)
        notes.extend(column_notes)
        columns.append(
            ColumnSchema(
                name=name,
                original_name=original.strip() or name,
                semantic_type=semantic_type,
                dtype=str(series.dtype),
            )
        )
    return TypedTable(frame=pd.DataFrame(converted), columns=columns, notes=notes)
