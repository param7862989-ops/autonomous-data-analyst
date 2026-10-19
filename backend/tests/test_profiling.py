from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.datasets.inference import infer_table
from app.datasets.ingest import IngestLimits, read_csv
from app.datasets.profiling import build_profile
from tests.factories import SAMPLE_SALES


def profile_for(text: str):  # type: ignore[no-untyped-def]
    raw = read_csv(text.encode(), IngestLimits(10_000, 50, 1_000_000, 1))
    typed = infer_table(raw.headers, raw.frame)
    return build_profile(typed.frame, typed.columns, typed.notes), typed


def test_numeric_stats_match_pandas() -> None:
    values = [3, 1, 4, 1, 5, 9, 2, 6, 5, 3, 5, 0, -2]
    profile, _ = profile_for("x\n" + "\n".join(map(str, values)) + "\n")
    stats = profile.columns[0].numeric
    assert stats is not None
    series = pd.Series(values, dtype="float64")
    assert stats.min == -2
    assert stats.max == 9
    assert stats.mean == pytest.approx(series.mean())
    assert stats.median == pytest.approx(series.median())
    assert stats.std == pytest.approx(series.std())
    assert stats.q1 == pytest.approx(series.quantile(0.25))
    assert stats.sum == pytest.approx(series.sum())
    assert stats.zeros == 1
    assert stats.negatives == 1
    histogram = profile.columns[0].histogram
    assert histogram is not None
    assert sum(b.count for b in histogram) == len(values)


def test_missing_counts_and_duplicates() -> None:
    profile, _ = profile_for("a,b\n1,x\n1,x\n,y\n4,\n")
    assert profile.row_count == 4
    assert profile.duplicate_row_count == 1
    assert profile.missing_cell_count == 2
    a = profile.columns[0]
    assert (a.non_null_count, a.missing_count, a.missing_share) == (3, 1, 0.25)
    codes = {w.code for w in profile.warnings}
    assert "duplicate_rows" in codes


def test_quality_warnings() -> None:
    rows = [f"{i},same,{'' if i % 3 else i},ID-{i},{1000 if i == 0 else i % 5}" for i in range(30)]
    profile, _ = profile_for("n,constant,sparse,code,spiky\n" + "\n".join(rows) + "\n")
    by_column = {(w.column, w.code) for w in profile.warnings}
    assert ("constant", "constant") in by_column
    assert ("sparse", "high_missing") in by_column
    assert ("code", "possible_identifier") in by_column
    assert ("spiky", "extreme_values") in by_column


def test_categorical_top_values_and_datetime_range() -> None:
    profile, _ = profile_for("d,cat\n2024-01-01,b\n2024-03-01,a\n2024-02-01,b\n")
    date_column, cat_column = profile.columns
    assert date_column.datetime is not None
    assert date_column.datetime.min == "2024-01-01T00:00:00"
    assert date_column.datetime.max == "2024-03-01T00:00:00"
    assert date_column.datetime.span_days == 60
    assert cat_column.top_values is not None
    assert [(v.value, v.count) for v in cat_column.top_values] == [("b", 2), ("a", 1)]


def test_profile_is_json_safe() -> None:
    profile, _ = profile_for("x,y\n1,\n,\n")
    dumped = profile.model_dump(mode="json")
    assert dumped["columns"][1]["semantic_type"] == "text"
    assert "NaN" not in str(dumped)


def test_sample_sales_dataset_profile() -> None:
    raw = read_csv(SAMPLE_SALES.read_bytes(), IngestLimits(100_000, 50, 10_000_000, 1))
    typed = infer_table(raw.headers, raw.frame)
    profile = build_profile(typed.frame, typed.columns, typed.notes)
    types = {c.name: c.semantic_type for c in typed.columns}
    assert types == {
        "order_id": "text",
        "order_date": "datetime",
        "region": "categorical",
        "product": "categorical",
        "category": "categorical",
        "sales_channel": "categorical",
        "units": "numeric",
        "unit_price": "numeric",
        "discount": "numeric",
        "revenue": "numeric",
    }
    expected = pd.read_csv(SAMPLE_SALES)
    revenue = next(c for c in profile.columns if c.name == "revenue").numeric
    assert revenue is not None
    assert revenue.sum == pytest.approx(expected["Revenue"].sum())
    discount = next(c for c in profile.columns if c.name == "discount")
    assert discount.missing_count == int(expected["Discount"].isna().sum())
    assert np.isfinite(profile.row_count)
    assert profile.row_count == len(expected)
