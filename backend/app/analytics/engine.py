"""A sandboxed DuckDB engine holding exactly one dataset.

Each analysis run gets its own in-memory DuckDB database containing a single table, ``data``,
loaded from the authorized dataset's Parquet file. Before any analytical query runs:

* external access is disabled (no files, URLs, extensions, ATTACH, COPY or EXPORT);
* configuration is locked, so a query cannot re-enable any of that or raise limits;
* threads and memory are capped.

Queries run with an interrupt-based timeout and a row cap. The engine never sees the
application database or any other user's data, so even a query that slipped past the SQL guard
could only read this one dataset.
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any, Protocol

import duckdb
from pydantic import BaseModel

from app.config import Settings
from app.jsonsafe import JsonScalar, rows_to_json

logger = logging.getLogger(__name__)

TABLE_NAME = "data"
# Text values in results are shortened to this many characters. Results are stored with the run
# and shown to the model; full values stay in the dataset.
MAX_CELL_CHARS = 1_000
# Error text from the engine is shown to the model (to let it fix its query) and possibly the
# user; anything that looks like a filesystem path is removed first.
_PATH_PATTERN = re.compile(r"([A-Za-z]:)?[\\/][^\s'\"]*[\\/][^\s'\"]*")


class AnalyticsError(Exception):
    """A failed analytical operation. ``message`` is safe to show to users and the model."""

    def __init__(self, message: str, *, code: str = "analysis_failed") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


class ResourceLimitError(AnalyticsError):
    def __init__(self) -> None:
        super().__init__(
            "The query needed more memory or time than allowed and was stopped. Simplify it "
            "or aggregate first.",
            code="query_resources",
        )


class QueryTimeoutError(AnalyticsError):
    def __init__(self, seconds: float) -> None:
        super().__init__(
            f"The query took longer than {seconds:g} seconds and was stopped.",
            code="query_timeout",
        )


@dataclass(frozen=True)
class EngineLimits:
    query_timeout_seconds: float = 10.0
    max_result_rows: int = 1_000
    memory_limit: str = "512MB"
    threads: int = 2

    @classmethod
    def from_settings(cls, settings: Settings) -> EngineLimits:
        return cls(
            query_timeout_seconds=settings.query_timeout_seconds,
            max_result_rows=settings.max_result_rows,
            memory_limit=settings.analytics_memory_limit,
            threads=settings.analytics_threads,
        )


class ResultColumn(BaseModel):
    name: str
    type: str


class TableResult(BaseModel):
    """Rows returned by the engine, JSON-safe, with a flag when the row cap cut them off."""

    columns: list[ResultColumn]
    rows: list[list[JsonScalar]]
    row_count: int
    truncated: bool

    def column_index(self, name: str) -> int:
        for index, column in enumerate(self.columns):
            if column.name == name:
                return index
        raise KeyError(name)

    def column_values(self, name: str) -> list[JsonScalar]:
        index = self.column_index(name)
        return [row[index] for row in self.rows]


class QueryEngine(Protocol):
    """What operations and tools need: run trusted SQL against the dataset."""

    def execute(self, sql: str, params: list[Any] | None = None) -> TableResult: ...

    def count_rows(self) -> int: ...


def _clip(value: Any) -> Any:
    if isinstance(value, str) and len(value) > MAX_CELL_CHARS:
        return value[: MAX_CELL_CHARS - 1] + "…"
    return value


def sanitize_engine_message(message: str) -> str:
    first_line = message.strip().splitlines()[0] if message.strip() else "Query failed."
    return _PATH_PATTERN.sub("<path>", first_line)[:500]


class AnalyticsEngine:
    def __init__(self, parquet_path: Path, limits: EngineLimits) -> None:
        self.limits = limits
        self._connection = duckdb.connect(
            ":memory:",
            config={
                "threads": limits.threads,
                "memory_limit": limits.memory_limit,
                "autoinstall_known_extensions": False,
                "autoload_known_extensions": False,
            },
        )
        try:
            self._connection.execute(
                f"CREATE TABLE {TABLE_NAME} AS SELECT * FROM read_parquet(?)",
                [str(parquet_path)],
            )
            # Order matters: lock last, so nothing after this point can change the sandbox.
            self._connection.execute("SET enable_external_access = false")
            self._connection.execute("SET lock_configuration = true")
        except Exception:
            self._connection.close()
            raise
        self._lock = threading.Lock()

    def __enter__(self) -> AnalyticsEngine:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._connection.close()

    def execute(self, sql: str, params: list[Any] | None = None) -> TableResult:
        """Run SQL that has already been validated or generated by trusted code.

        The SQL guard (for model-written SQL) and the typed operations are the only callers.
        """
        with self._lock:
            timer = threading.Timer(self.limits.query_timeout_seconds, self._connection.interrupt)
            timer.start()
            try:
                cursor = self._connection.execute(sql, params or [])
                description = cursor.description or []
                raw_rows = cursor.fetchmany(self.limits.max_result_rows + 1)
            except duckdb.InterruptException as exc:
                raise QueryTimeoutError(self.limits.query_timeout_seconds) from exc
            except duckdb.OutOfMemoryException as exc:
                raise ResourceLimitError() from exc
            except duckdb.Error as exc:
                logger.info("Analytical query failed: %s", type(exc).__name__)
                raise AnalyticsError(
                    sanitize_engine_message(str(exc)), code="query_failed"
                ) from exc
            finally:
                timer.cancel()
        truncated = len(raw_rows) > self.limits.max_result_rows
        rows = raw_rows[: self.limits.max_result_rows]
        return TableResult(
            columns=[ResultColumn(name=str(d[0]), type=str(d[1])) for d in description],
            rows=[[_clip(value) for value in row] for row in rows_to_json(rows)],
            row_count=len(rows),
            truncated=truncated,
        )

    def count_rows(self) -> int:
        result = self.execute(f"SELECT COUNT(*) FROM {TABLE_NAME}")
        value = result.rows[0][0]
        return int(value) if isinstance(value, int) else 0
