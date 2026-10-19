"""In-process sliding-window rate limiter.

Limits are per process. With several worker processes the effective limit is multiplied by the
worker count; a shared store (e.g. Redis) would be needed for exact global limits. This trade-off
is documented in docs/KNOWN_LIMITATIONS.md.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from collections.abc import Callable

from app.errors import RateLimitedError

_MAX_KEYS = 50_000


class RateLimiter:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._hits: dict[tuple[str, str], deque[float]] = {}

    def _window(self, bucket: str, key: str, window_seconds: float, now: float) -> deque[float]:
        hits = self._hits.setdefault((bucket, key), deque())
        while hits and hits[0] <= now - window_seconds:
            hits.popleft()
        return hits

    def check(self, bucket: str, key: str, *, limit: int, window_seconds: float) -> None:
        """Raise ``RateLimitedError`` if ``limit`` hits already happened within the window."""
        with self._lock:
            now = self._clock()
            hits = self._window(bucket, key, window_seconds, now)
            if len(hits) >= limit:
                retry_after = max(1, math.ceil(hits[0] + window_seconds - now))
                raise RateLimitedError(
                    "Too many attempts. Wait a moment and try again.",
                    details={"retry_after": retry_after},
                )

    def record(self, bucket: str, key: str, *, window_seconds: float) -> None:
        with self._lock:
            now = self._clock()
            self._window(bucket, key, window_seconds, now).append(now)
            if len(self._hits) > _MAX_KEYS:
                self._prune(now)

    def hit(self, bucket: str, key: str, *, limit: int, window_seconds: float) -> None:
        """Check, then record one attempt."""
        self.check(bucket, key, limit=limit, window_seconds=window_seconds)
        self.record(bucket, key, window_seconds=window_seconds)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()

    def _prune(self, now: float) -> None:
        # Drop keys with no hits in the last hour (longest window in use).
        stale = [k for k, hits in self._hits.items() if not hits or hits[-1] <= now - 3600]
        for key in stale:
            del self._hits[key]
