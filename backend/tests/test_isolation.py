"""The process-isolated engine: same results, errors mapped, crashes and hangs recovered, and
(on Linux) a memory cap that stops string-amplifying queries."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd
import pytest

from app.analytics import isolation
from app.analytics.engine import (
    AnalyticsEngine,
    AnalyticsError,
    EngineLimits,
    QueryTimeoutError,
    ResourceLimitError,
)
from app.analytics.isolation import IsolatedEngine, scrub_environment
from app.config import Settings


@pytest.fixture(scope="module")
def parquet(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("iso") / "data.parquet"
    pd.DataFrame(
        {"product": [f"product-{i}" for i in range(50_000)], "n": range(50_000)}
    ).to_parquet(path)
    return path


def test_results_match_the_in_process_engine(parquet: Path) -> None:
    sql = "SELECT product, n FROM data ORDER BY n DESC LIMIT 3"
    with AnalyticsEngine(parquet, EngineLimits()) as local:
        expected = local.execute(sql)
    with IsolatedEngine(parquet, EngineLimits(), address_space_bytes=None) as isolated:
        assert isolated.execute(sql) == expected
        assert isolated.count_rows() == 50_000
        with pytest.raises(AnalyticsError) as excinfo:
            isolated.execute("SELECT missing FROM data")
        assert excinfo.value.code == "query_failed"
        # Still usable after an error.
        assert isolated.count_rows() == 50_000


def test_a_dead_engine_is_restarted(parquet: Path) -> None:
    with IsolatedEngine(parquet, EngineLimits(), address_space_bytes=None) as engine:
        engine._process.kill()
        engine._process.join(5)
        assert engine.count_rows() == 50_000


def test_a_hung_query_is_killed_and_the_engine_restarts(
    parquet: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(isolation, "_GRACE_SECONDS", 0.0)
    limits = EngineLimits(query_timeout_seconds=0.05)
    with IsolatedEngine(parquet, limits, address_space_bytes=None) as engine:
        with pytest.raises(QueryTimeoutError):
            engine.execute("SELECT COUNT(*) FROM data a, data b WHERE a.n + b.n = -1")
        assert engine.count_rows() == 50_000
        # Either the child interrupted itself or the parent killed it; both must recover.
        assert engine._process is not None


def test_a_timeout_inside_the_engine_keeps_its_error_type(parquet: Path) -> None:
    # With the default grace period the child's own DuckDB interrupt fires first; the error
    # crosses the process boundary and must still be a QueryTimeoutError.
    with IsolatedEngine(
        parquet, EngineLimits(query_timeout_seconds=0.3), address_space_bytes=None
    ) as engine:
        process = engine._process
        with pytest.raises(QueryTimeoutError):
            engine.execute("SELECT COUNT(*) FROM data a, data b WHERE a.n + b.n = -1")
        assert engine._process is process, "the child should not have been killed"
        assert engine.count_rows() == 50_000


@pytest.mark.skipif(sys.platform == "win32", reason="RLIMIT_AS is only available on Linux/macOS")
def test_memory_cap_stops_string_amplification(parquet: Path) -> None:
    # Bypasses the SQL guard on purpose: REPEAT is not allowlisted. This is the sandbox's own
    # defence against anything that might slip through. The cap is the production default:
    # the child needs about 1.3 GB of address space before any query (measured), so a much
    # smaller cap would stop the engine from starting at all.
    cap = Settings.model_fields["analytics_process_memory_bytes"].default
    with IsolatedEngine(parquet, EngineLimits(), address_space_bytes=cap) as engine:
        with pytest.raises(ResourceLimitError):
            engine.execute("SELECT SUM(LENGTH(REPEAT(product, 1000000))) FROM data")
        assert engine.count_rows() == 50_000


def test_long_text_values_are_clipped(tmp_path: Path) -> None:
    path = tmp_path / "long.parquet"
    pd.DataFrame({"note": ["x" * 5_000]}).to_parquet(path)
    with AnalyticsEngine(path, EngineLimits()) as engine:
        value = engine.execute("SELECT note FROM data").rows[0][0]
    assert isinstance(value, str)
    assert len(value) == 1_000


def test_secrets_are_scrubbed_from_the_child_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h/db")
    monkeypatch.setenv("POSTGRES_PASSWORD", "pw")
    monkeypatch.setenv("HARMLESS_SETTING", "keep")
    removed = scrub_environment()
    assert {"ANTHROPIC_API_KEY", "DATABASE_URL", "POSTGRES_PASSWORD"} <= set(removed)
    assert "ANTHROPIC_API_KEY" not in os.environ
    assert os.environ["HARMLESS_SETTING"] == "keep"
