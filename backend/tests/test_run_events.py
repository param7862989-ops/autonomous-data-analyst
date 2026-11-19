"""Live analysis updates: the notifier (unit) and the Server-Sent Events endpoint (API)."""

from __future__ import annotations

import asyncio
import json
import threading
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.errors import RateLimitedError
from app.main import create_app
from app.services.run_events import RunNotifier
from tests.conftest import CSRF_HEADERS, make_settings, register
from tests.scripted import HoldingExecutor, InlineExecutor, sales_provider
from tests.test_analyses_api import ask, new_conversation, upload_sales

# --- RunNotifier -----------------------------------------------------------------------------


def test_notify_from_another_thread_wakes_subscribers_of_that_run_only() -> None:
    notifier = RunNotifier(max_streams_per_user=2)
    run_id, other = uuid.uuid4(), uuid.uuid4()

    async def scenario() -> tuple[bool, bool]:
        with notifier.subscribe(run_id) as mine, notifier.subscribe(other) as theirs:
            thread = threading.Thread(target=notifier.notify, args=(run_id,))
            thread.start()
            thread.join()
            await asyncio.wait_for(mine.wait(), timeout=2)
            return mine.is_set(), theirs.is_set()

    assert asyncio.run(scenario()) == (True, False)
    notifier.notify(run_id)  # no subscribers left: a no-op


def test_subscriptions_are_removed_on_exit() -> None:
    notifier = RunNotifier(max_streams_per_user=2)
    run_id = uuid.uuid4()

    async def scenario() -> None:
        with notifier.subscribe(run_id):
            assert run_id in notifier._waiters
        assert run_id not in notifier._waiters

    asyncio.run(scenario())


def test_streams_per_user_are_limited_and_released() -> None:
    notifier = RunNotifier(max_streams_per_user=2)
    alice, bob = uuid.uuid4(), uuid.uuid4()
    with notifier.reserve(alice), notifier.reserve(alice):
        with pytest.raises(RateLimitedError), notifier.reserve(alice):
            pass
        with notifier.reserve(bob):  # limits are per user
            assert notifier.open_streams() == 3
    assert notifier.open_streams() == 0
    with notifier.reserve(alice):
        pass


# --- The endpoint ----------------------------------------------------------------------------


def parse(lines: Iterator[str]) -> Iterator[tuple[str, dict[str, Any]]]:
    """Yields (event, data) pairs from an event stream; skips keep-alive comments."""
    event: str | None = None
    for line in lines:
        if line.startswith("event: "):
            event = line.removeprefix("event: ")
        elif line.startswith("data: ") and event is not None:
            yield event, json.loads(line.removeprefix("data: "))
            event = None


def stream_app(tmp_path: Path, executor: Any, **settings: object) -> Any:
    values: dict[str, object] = {
        "event_stream_check_seconds": 0.1,
        "event_stream_keepalive_seconds": 1,
    }
    values.update(settings)
    return create_app(
        make_settings(tmp_path, **values), provider_factory=sales_provider, run_executor=executor
    )


def start(client: TestClient) -> dict[str, Any]:
    register(client)
    return ask(client, new_conversation(client, upload_sales(client)))


@pytest.mark.db
def test_stream_follows_a_run_from_queued_to_completed(db_engine: Engine, tmp_path: Path) -> None:
    holding = HoldingExecutor()
    with TestClient(stream_app(tmp_path, holding), headers=CSRF_HEADERS) as client:
        run = start(client)
        with client.stream("GET", f"/api/analyses/{run['id']}/events") as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            assert "no-transform" in response.headers["cache-control"]
            events = parse(response.iter_lines())
            name, first = next(events)
            assert (name, first["status"]) == ("run", "queued")

            # The worker runs now; its commits wake the stream.
            fn, args = holding.held[0]
            worker = threading.Thread(target=fn, args=args)
            worker.start()
            seen = [data for _, data in events]
            worker.join()

    statuses = [data["status"] for data in seen]
    assert statuses[-1] == "completed"
    assert "running" in statuses
    # Progress arrives step by step, not only as one final state.
    assert len({len(data["events"]) for data in seen}) > 2
    final = seen[-1]
    assert final["outcome"]["answer"]["summary"]
    # The final event is exactly what the polling endpoint returns.
    assert final == client.get(f"/api/analyses/{run['id']}").json()


@pytest.mark.db
def test_stream_of_a_finished_run_sends_it_once_and_closes(
    db_engine: Engine, tmp_path: Path
) -> None:
    with TestClient(stream_app(tmp_path, InlineExecutor()), headers=CSRF_HEADERS) as client:
        run = start(client)
        with client.stream("GET", f"/api/analyses/{run['id']}/events") as response:
            events = list(parse(response.iter_lines()))
    assert [(name, data["status"]) for name, data in events] == [("run", "completed")]


@pytest.mark.db
def test_stream_shows_cancellation(db_engine: Engine, tmp_path: Path) -> None:
    with TestClient(stream_app(tmp_path, HoldingExecutor()), headers=CSRF_HEADERS) as client:
        run = start(client)
        with client.stream("GET", f"/api/analyses/{run['id']}/events") as response:
            events = parse(response.iter_lines())
            assert next(events)[1]["status"] == "queued"
            assert client.post(f"/api/analyses/{run['id']}/cancel").status_code == 202
            assert [data["status"] for _, data in events] == ["cancelled"]


@pytest.mark.db
def test_stream_is_private_to_the_owner(db_engine: Engine, tmp_path: Path) -> None:
    app = stream_app(tmp_path, HoldingExecutor())
    with TestClient(app, headers=CSRF_HEADERS) as owner:
        run = start(owner)
        with TestClient(app, headers=CSRF_HEADERS) as anonymous:
            assert anonymous.get(f"/api/analyses/{run['id']}/events").status_code == 401
        with TestClient(app, headers=CSRF_HEADERS) as intruder:
            register(intruder, email="mallory@example.com")
            response = intruder.get(f"/api/analyses/{run['id']}/events")
            assert response.status_code == 404
            assert response.json()["error"]["code"] == "not_found"


@pytest.mark.db
def test_signing_out_ends_the_stream(db_engine: Engine, tmp_path: Path) -> None:
    app = stream_app(tmp_path, HoldingExecutor())
    with TestClient(app, headers=CSRF_HEADERS) as client:
        run = start(client)
        with client.stream("GET", f"/api/analyses/{run['id']}/events") as response:
            events = parse(response.iter_lines())
            assert next(events)[0] == "run"
            # Sign out from another tab with the same session cookie.
            with TestClient(app, headers=CSRF_HEADERS, cookies=client.cookies) as tab:
                assert tab.post("/api/auth/logout").status_code == 204
            assert list(events) == [("end", {"reason": "session_ended"})]


@pytest.mark.db
def test_open_streams_per_user_are_limited(db_engine: Engine, tmp_path: Path) -> None:
    # A short lifetime keeps a failure from hanging for the default five minutes.
    app = stream_app(
        tmp_path, HoldingExecutor(), event_streams_per_user=1, event_stream_max_seconds=10
    )
    with TestClient(app, headers=CSRF_HEADERS) as client:
        run = start(client)
        url = f"/api/analyses/{run['id']}/events"
        with client.stream("GET", url) as first:
            # Keep a reference: a discarded line iterator closes the response, which would
            # end the first stream and free its slot.
            first_events = parse(first.iter_lines())
            assert next(first_events)[0] == "run"
            with client.stream("GET", url) as second:
                assert list(parse(second.iter_lines())) == [
                    ("end", {"reason": "too_many_streams"})
                ]
        # The first stream's slot is released when it closes.
        with client.stream("GET", url) as third:
            third_events = parse(third.iter_lines())
            assert next(third_events)[0] == "run"


@pytest.mark.db
def test_stream_ends_at_its_maximum_lifetime(db_engine: Engine, tmp_path: Path) -> None:
    app = stream_app(tmp_path, HoldingExecutor(), event_stream_max_seconds=10)
    with TestClient(app, headers=CSRF_HEADERS) as client:
        run = start(client)
        app.state.settings.event_stream_max_seconds = 0.3  # shorter than the minimum, for speed
        with client.stream("GET", f"/api/analyses/{run['id']}/events") as response:
            events = list(parse(response.iter_lines()))
    assert events[0][0] == "run"
    assert events[-1] == ("end", {"reason": "timeout"})
