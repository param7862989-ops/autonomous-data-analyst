from __future__ import annotations

import datetime as dt
from typing import Any

import pandas as pd
import pytest

from app.datasets.inference import infer_column, infer_table, normalize_headers


def infer(values: list[Any]) -> tuple[list[Any], str, list[str]]:
    series, semantic_type, notes = infer_column(pd.Series(values, dtype=object), "col")
    return series.tolist(), semantic_type, [note.code for note in notes]


def test_header_normalization() -> None:
    names, notes = normalize_headers(
        ["Order Date", "Revenue ($)", "", "Revenue ($)", "2024 Sales", "Ünïcödé", "  "]
    )
    assert names == [
        "order_date",
        "revenue",
        "column_3",
        "revenue_2",
        "c_2024_sales",
        "unicode",
        "column_7",
    ]
    assert sorted({note.code for note in notes}) == ["duplicate_header", "empty_header"]


def test_header_dedupe_does_not_collide_with_existing_suffix() -> None:
    names, _ = normalize_headers(["a", "a_2", "a"])
    assert names == ["a", "a_2", "a_3"]
    assert len(set(names)) == 3


def test_integers_and_floats() -> None:
    values, kind, _ = infer(["1", "2", "3"])
    assert kind == "numeric"
    assert values == [1, 2, 3]
    values, kind, _ = infer(["1.5", "2", "-3e2"])
    assert values == [1.5, 2.0, -300.0]


def test_formatted_numbers() -> None:
    values, kind, notes = infer(["$1,234.50", "(200.00)", "-$5", "€ 3", "12%"])
    assert kind == "numeric"
    assert values == [1234.5, -200.0, -5.0, 3.0, 12.0]
    assert "percent_values" in notes


def test_missing_tokens() -> None:
    values, kind, _ = infer(["1", "", "NA", "n/a", "null", "#N/A", "-", "4"])
    assert kind == "numeric"
    assert values[0] == 1
    assert values[-1] == 4
    assert all(pd.isna(v) for v in values[1:-1])


def test_a_few_bad_values_become_missing_and_are_reported() -> None:
    values, kind, notes = infer([str(i) for i in range(40)] + ["oops"])
    assert kind == "numeric"
    assert pd.isna(values[-1])
    assert notes == ["unparsed_values"]


def test_mixed_column_stays_text() -> None:
    _, kind, notes = infer(["1", "2", "three", "4", "five", "6"])
    assert kind in ("categorical", "text")
    assert notes == ["mixed_types"]


def test_leading_zero_codes_stay_text() -> None:
    values, kind, notes = infer(["02134", "00501", "10001", "94105"])
    assert kind == "categorical"
    assert values == ["02134", "00501", "10001", "94105"]
    assert notes == ["kept_as_text"]


def test_iso_dates_and_datetimes() -> None:
    values, kind, _ = infer(["2024-01-05", "2024-02-01T10:30:00", None])
    assert kind == "datetime"
    assert values[0] == pd.Timestamp("2024-01-05")
    assert values[1] == pd.Timestamp("2024-02-01 10:30:00")
    assert pd.isna(values[2])


def test_timezone_offsets_are_normalized_to_utc() -> None:
    values, kind, _ = infer(["2024-01-05T10:00:00+02:00", "2024-01-05T10:00:00Z"])
    assert kind == "datetime"
    assert values == [pd.Timestamp("2024-01-05 08:00:00"), pd.Timestamp("2024-01-05 10:00:00")]


def test_unambiguous_day_first_dates() -> None:
    values, kind, notes = infer(["31/12/2024", "15/01/2024", "01/02/2024"])
    assert kind == "datetime"
    assert values[0] == pd.Timestamp("2024-12-31")
    assert values[2] == pd.Timestamp("2024-02-01")
    assert "ambiguous_dates" not in notes


def test_ambiguous_dates_assume_month_first_and_warn() -> None:
    values, kind, notes = infer(["01/02/2024", "03/04/2024"])
    assert kind == "datetime"
    assert values[0] == pd.Timestamp("2024-01-02")
    assert "ambiguous_dates" in notes


def test_years_are_numbers_not_dates() -> None:
    _, kind, _ = infer(["2021", "2022", "2023"])
    assert kind == "numeric"


def test_native_excel_values() -> None:
    values, kind, _ = infer([dt.datetime(2024, 1, 1), dt.date(2024, 2, 1), None])
    assert kind == "datetime"
    assert values[1] == pd.Timestamp("2024-02-01")
    values, kind, _ = infer([1, 2.5, None])
    assert kind == "numeric"


@pytest.mark.parametrize(
    "values", [["yes", "No", "TRUE", "false"], [True, False, None], ["y", "n", "t", "f"]]
)
def test_booleans(values: list[Any]) -> None:
    converted, kind, _ = infer(values)
    assert kind == "boolean"
    assert converted[0] is True


def test_zero_one_is_numeric_not_boolean() -> None:
    _, kind, _ = infer(["0", "1", "1", "0"])
    assert kind == "numeric"


def test_categorical_vs_text() -> None:
    _, kind, _ = infer(["North", "South"] * 50)
    assert kind == "categorical"
    _, kind, _ = infer([f"free text comment number {i}" for i in range(100)])
    assert kind == "text"


def test_missing_text_values_stay_missing() -> None:
    values, kind, _ = infer(["x", "", None, "y", "NA"])
    assert kind == "categorical"
    assert values[0] == "x"
    assert values[3] == "y"
    assert all(pd.isna(values[i]) for i in (1, 2, 4))
    assert "nan" not in [str(v).lower() for v in values if not pd.isna(v)]


def test_all_missing_column() -> None:
    values, kind, notes = infer([None, "", "NA"])
    assert kind == "text"
    assert all(pd.isna(v) for v in values)
    assert notes == ["all_missing"]


def test_infer_table_preserves_original_names_and_order() -> None:
    frame = pd.DataFrame([["2024-01-01", "5"], ["2024-01-02", "7"]], dtype=object)
    frame.columns = [0, 1]
    table = infer_table(["Order Date", "Units"], frame)
    assert [c.name for c in table.columns] == ["order_date", "units"]
    assert [c.original_name for c in table.columns] == ["Order Date", "Units"]
    assert [c.semantic_type for c in table.columns] == ["datetime", "numeric"]
    assert list(table.frame.columns) == ["order_date", "units"]
