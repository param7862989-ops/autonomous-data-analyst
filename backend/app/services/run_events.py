"""Wakes live-update streams when an analysis run changes.

Runs execute in worker threads; streams are async generators on the event loop. A worker calls
``notify(run_id)`` after committing a change, and every stream subscribed to that run wakes up
and re-reads the run from the database. The database stays the source of truth: a stream also
re-reads on a short timer, so a missed or cross-process change (several workers) is picked up
within that interval, just more slowly.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
import uuid
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager

from app.errors import RateLimitedError


class RunNotifier:
    def __init__(self, *, max_streams_per_user: int) -> None:
        self._lock = threading.Lock()
        self._waiters: dict[uuid.UUID, set[tuple[asyncio.AbstractEventLoop, asyncio.Event]]] = (
            defaultdict(set)
        )
        self._streams_per_user: dict[uuid.UUID, int] = defaultdict(int)
        self._max_streams_per_user = max_streams_per_user

    def notify(self, run_id: uuid.UUID) -> None:
        """Safe to call from any thread."""
        with self._lock:
            waiters = list(self._waiters.get(run_id, ()))
        for loop, event in waiters:
            # RuntimeError: that loop has closed, so its stream is gone.
            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(event.set)

    @contextmanager
    def reserve(self, user_id: uuid.UUID) -> Iterator[None]:
        """Count an open stream against the user's limit (each one holds a connection)."""
        with self._lock:
            if self._streams_per_user[user_id] >= self._max_streams_per_user:
                raise RateLimitedError(
                    "Too many live updates are open. Close a tab or wait for an analysis to end."
                )
            self._streams_per_user[user_id] += 1
        try:
            yield
        finally:
            with self._lock:
                self._streams_per_user[user_id] -= 1
                if self._streams_per_user[user_id] <= 0:
                    del self._streams_per_user[user_id]

    @contextmanager
    def subscribe(self, run_id: uuid.UUID) -> Iterator[asyncio.Event]:
        """An event set whenever the run changes. Must be entered on the event loop."""
        entry = (asyncio.get_running_loop(), asyncio.Event())
        with self._lock:
            self._waiters[run_id].add(entry)
        try:
            yield entry[1]
        finally:
            with self._lock:
                waiters = self._waiters.get(run_id)
                if waiters is not None:
                    waiters.discard(entry)
                    if not waiters:
                        del self._waiters[run_id]

    def open_streams(self) -> int:
        with self._lock:
            return sum(self._streams_per_user.values())
