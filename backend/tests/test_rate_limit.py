from __future__ import annotations

import pytest

from app.auth.rate_limit import RateLimiter
from app.errors import RateLimitedError


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_allows_up_to_limit_then_blocks_with_retry_after() -> None:
    limiter = RateLimiter(FakeClock())
    for _ in range(3):
        limiter.hit("b", "k", limit=3, window_seconds=60)
    with pytest.raises(RateLimitedError) as excinfo:
        limiter.hit("b", "k", limit=3, window_seconds=60)
    assert excinfo.value.details == {"retry_after": 60}


def test_window_slides() -> None:
    clock = FakeClock()
    limiter = RateLimiter(clock)
    limiter.hit("b", "k", limit=1, window_seconds=60)
    clock.now += 61
    limiter.hit("b", "k", limit=1, window_seconds=60)  # does not raise


def test_keys_and_buckets_are_independent() -> None:
    limiter = RateLimiter(FakeClock())
    limiter.hit("b", "k1", limit=1, window_seconds=60)
    limiter.hit("b", "k2", limit=1, window_seconds=60)
    limiter.hit("other", "k1", limit=1, window_seconds=60)


def test_check_does_not_record() -> None:
    limiter = RateLimiter(FakeClock())
    for _ in range(5):
        limiter.check("b", "k", limit=1, window_seconds=60)
