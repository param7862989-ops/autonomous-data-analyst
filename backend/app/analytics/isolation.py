"""Run the analytical engine in a separate, resource-capped process.

DuckDB's ``memory_limit`` governs its buffer manager, but not every allocation (scalar string
results, for one). So the engine used for model-driven analysis runs in a child process:

* on Linux the child's address space is capped with ``RLIMIT_AS``: an allocation beyond it fails
  inside DuckDB with an out-of-memory error instead of exhausting the server (measured: a
  string-amplifying query raises ``OutOfMemoryException`` and the child keeps working);
* if a query does not return within its timeout plus a grace period, the child is killed and a
  fresh one is started for the next query;
* if the child dies, the query fails with a clear error and the next query restarts it.

The child receives only the dataset path and limits. It removes secret-looking environment
variables it inherited (API keys, database URL, passwords) before loading anything, and DuckDB
inside it has no file or network access. On Windows,
where ``resource`` is unavailable, only the kill-on-timeout protection applies.
"""

from __future__ import annotations

import logging
import multiprocessing
import os
import sys
import threading
from multiprocessing.connection import Connection
from pathlib import Path
from types import TracebackType
from typing import Any

from app.analytics.engine import (
    AnalyticsEngine,
    AnalyticsError,
    EngineLimits,
    QueryTimeoutError,
    ResourceLimitError,
    TableResult,
)

logger = logging.getLogger(__name__)

_STARTUP_SECONDS = 120.0
_GRACE_SECONDS = 5.0
_context = multiprocessing.get_context("spawn")


_SECRET_MARKERS = ("KEY", "SECRET", "TOKEN", "PASSWORD", "DATABASE_URL", "CREDENTIAL")


def scrub_environment() -> list[str]:
    """Remove secret-looking variables inherited from the parent. Returns the names removed."""
    removed = [name for name in os.environ if any(m in name.upper() for m in _SECRET_MARKERS)]
    for name in removed:
        del os.environ[name]
    return removed


def _apply_memory_cap(address_space_bytes: int | None) -> None:
    if not address_space_bytes or sys.platform == "win32":
        return
    import resource

    resource.setrlimit(resource.RLIMIT_AS, (address_space_bytes, address_space_bytes))


def _worker(
    connection: Connection, path: str, limits: EngineLimits, address_space_bytes: int | None
) -> None:
    """Child process: own one engine and answer queries until told to stop."""
    try:
        scrub_environment()
        _apply_memory_cap(address_space_bytes)
        engine = AnalyticsEngine(Path(path), limits)
    except Exception as exc:  # noqa: BLE001 - reported to the parent, which raises
        connection.send(("failed", type(exc).__name__))
        return
    connection.send(("ready", None))
    with engine:
        while True:
            try:
                message = connection.recv()
            except (EOFError, OSError):
                return
            if message[0] == "close":
                return
            _, sql, params = message
            try:
                connection.send(("ok", engine.execute(sql, params).model_dump()))
            except AnalyticsError as exc:
                connection.send(("error", (exc.message, exc.code)))
            except MemoryError:
                connection.send(("error", None))


class IsolatedEngine:
    """Same interface as :class:`AnalyticsEngine`, executed in a capped child process."""

    def __init__(
        self, parquet_path: Path, limits: EngineLimits, *, address_space_bytes: int | None
    ) -> None:
        self.limits = limits
        self._path = str(parquet_path)
        self._address_space = address_space_bytes
        self._lock = threading.Lock()
        self._process: Any = None
        # multiprocessing returns a platform-specific connection type (PipeConnection on Windows).
        self._connection: Any = None
        self._start()

    def __enter__(self) -> IsolatedEngine:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def _start(self) -> None:
        parent, child = _context.Pipe()
        process = _context.Process(
            target=_worker,
            args=(child, self._path, self.limits, self._address_space),
            daemon=True,
            name="analytics-engine",
        )
        process.start()
        child.close()
        self._process, self._connection = process, parent
        if not parent.poll(_STARTUP_SECONDS):
            self._kill()
            raise AnalyticsError("The analysis engine did not start in time.", code="engine_failed")
        try:
            status, detail = parent.recv()
        except EOFError as exc:
            self._kill()
            raise AnalyticsError(
                "The analysis engine failed to start.", code="engine_failed"
            ) from exc
        if status != "ready":
            self._kill()
            logger.error("Analytics engine failed to start: %s", detail)
            raise AnalyticsError(
                "The dataset could not be loaded for analysis.", code="engine_failed"
            )

    def _kill(self) -> None:
        if self._process is not None and self._process.is_alive():
            self._process.kill()
            self._process.join(5)
        if self._connection is not None:
            self._connection.close()
        self._process, self._connection = None, None

    def execute(self, sql: str, params: list[Any] | None = None) -> TableResult:
        with self._lock:
            if self._process is None or not self._process.is_alive():
                self._kill()
                self._start()
            assert self._connection is not None
            try:
                self._connection.send(("execute", sql, params or []))
                ready = self._connection.poll(self.limits.query_timeout_seconds + _GRACE_SECONDS)
            except (BrokenPipeError, OSError) as exc:
                self._kill()
                raise ResourceLimitError() from exc
            if not ready:
                logger.warning("Analytics query exceeded its hard deadline; killing the engine")
                self._kill()
                raise QueryTimeoutError(self.limits.query_timeout_seconds)
            try:
                status, payload = self._connection.recv()
            except EOFError as exc:
                logger.warning("Analytics engine process died during a query")
                self._kill()
                raise ResourceLimitError() from exc
        if status == "ok":
            return TableResult.model_validate(payload)
        if payload is None:
            raise ResourceLimitError()
        message, code = payload
        # Rebuild the specific error types so callers see what the in-process engine raises.
        if code == "query_resources":
            raise ResourceLimitError()
        if code == "query_timeout":
            raise QueryTimeoutError(self.limits.query_timeout_seconds)
        raise AnalyticsError(message, code=code)

    def count_rows(self) -> int:
        value = self.execute("SELECT COUNT(*) FROM data").rows[0][0]
        return int(value) if isinstance(value, int) else 0

    def close(self) -> None:
        with self._lock:
            if self._connection is not None and self._process is not None:
                try:
                    self._connection.send(("close",))
                    self._process.join(2)
                except (BrokenPipeError, OSError):
                    pass
            self._kill()
