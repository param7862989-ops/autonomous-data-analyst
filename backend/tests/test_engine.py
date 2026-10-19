from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from app.analytics.engine import (
    AnalyticsEngine,
    AnalyticsError,
    EngineLimits,
    QueryTimeoutError,
    sanitize_engine_message,
)
from app.analytics.sql_guard import validate_sql


@pytest.fixture
def small_engine(tmp_path: Path) -> AnalyticsEngine:
    path = tmp_path / "d.parquet"
    pd.DataFrame(
        {
            "n": [1, 2, 3, None],
            "d": pd.to_datetime(["2024-01-01", "2024-02-01", None, "2024-03-01"]),
            "s": ["a", "b", None, "d"],
            "f": [0.5, float("nan"), 2.5, 3.5],
        }
    ).to_parquet(path)
    return AnalyticsEngine(path, EngineLimits(query_timeout_seconds=1, max_result_rows=2))


def test_results_are_json_safe_and_typed(small_engine: AnalyticsEngine) -> None:
    result = small_engine.execute("SELECT n, d, s, f FROM data ORDER BY n NULLS LAST LIMIT 2")
    assert [c.name for c in result.columns] == ["n", "d", "s", "f"]
    assert result.rows == [
        [1.0, "2024-01-01T00:00:00", "a", 0.5],
        [2.0, "2024-02-01T00:00:00", "b", None],
    ]


def test_row_cap_sets_truncated(small_engine: AnalyticsEngine) -> None:
    result = small_engine.execute("SELECT * FROM data")
    assert result.row_count == 2
    assert result.truncated is True


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM read_csv('/etc/passwd')",
        "SELECT * FROM read_text('C:/Windows/win.ini')",
        "COPY data TO 'out.csv'",
        "ATTACH 'other.db'",
        "INSTALL httpfs",
        "SET enable_external_access = true",
        "SET lock_configuration = false",
        "SET memory_limit = '64GB'",
    ],
)
def test_sandbox_blocks_escapes_even_without_the_guard(
    small_engine: AnalyticsEngine, sql: str
) -> None:
    # Defence in depth: these never get past validate_sql, but the engine refuses them too.
    with pytest.raises(AnalyticsError):
        small_engine.execute(sql)


def test_only_the_dataset_is_visible(small_engine: AnalyticsEngine) -> None:
    tables = small_engine.execute("SELECT table_name FROM information_schema.tables")
    assert tables.rows == [["data"]]


def test_timeout_interrupts_long_queries(tmp_path: Path) -> None:
    path = tmp_path / "d.parquet"
    pd.DataFrame({"x": range(3_000)}).to_parquet(path)
    with AnalyticsEngine(path, EngineLimits(query_timeout_seconds=0.5)) as engine:
        sql = validate_sql("SELECT COUNT(*) FROM data a, data b, data c WHERE a.x + b.x > c.x")
        with pytest.raises(QueryTimeoutError):
            engine.execute(sql)
        # The engine is still usable afterwards.
        assert engine.count_rows() == 3_000


def test_errors_are_sanitized(small_engine: AnalyticsEngine) -> None:
    with pytest.raises(AnalyticsError) as excinfo:
        small_engine.execute("SELECT missing_column FROM data")
    assert "missing_column" in excinfo.value.message
    assert excinfo.value.code == "query_failed"


def test_sanitize_engine_message_removes_paths() -> None:
    message = 'IO Error: Cannot open "C:/srv/storage/datasets/abc/def.parquet"\nmore detail'
    cleaned = sanitize_engine_message(message)
    assert "storage" not in cleaned
    assert "more detail" not in cleaned
    assert "/home/app/x" not in sanitize_engine_message("failed /home/app/x y")
