"""Analysis runs: progress, results, cancellation and history."""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Literal

import anyio
from fastapi import APIRouter, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.agent.schemas import AgentOutcome
from app.api.deps import CurrentUser, DbSession, SettingsDep
from app.auth.service import resolve_session
from app.db.models import AnalysisRun
from app.errors import RateLimitedError
from app.schemas.analyses import (
    ActivityEventOut,
    HistoryItem,
    HistoryList,
    RunDetail,
    RunSummary,
)
from app.services import conversations as service
from app.services.run_events import RunNotifier

router = APIRouter(prefix="/analyses", tags=["analyses"])


def _outcome(run: AnalysisRun) -> AgentOutcome | None:
    return AgentOutcome.model_validate(run.outcome) if run.outcome else None


def run_summary(run: AnalysisRun) -> RunSummary:
    outcome = _outcome(run)
    return RunSummary(
        id=run.id,
        conversation_id=run.conversation_id,
        dataset_id=run.dataset_id,
        question=run.question,
        status=run.status,
        stop_reason=run.stop_reason,
        answer_summary=outcome.answer.summary if outcome and outcome.answer else None,
        created_at=run.created_at,
        finished_at=run.finished_at,
    )


@router.get("", response_model=HistoryList, summary="Your analysis history")
def list_analyses(
    user: CurrentUser,
    db: DbSession,
    dataset_id: uuid.UUID | None = None,
    conversation_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> HistoryList:
    rows, total = service.list_runs(
        db,
        user=user,
        dataset_id=dataset_id,
        conversation_id=conversation_id,
        limit=limit,
        offset=offset,
    )
    return HistoryList(
        items=[
            HistoryItem(**run_summary(run).model_dump(), dataset_name=name) for run, name in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{run_id}",
    response_model=RunDetail,
    summary="An analysis: status, activity and result",
    description="Poll while `status` is `queued` or `running`.",
)
def get_analysis(run_id: uuid.UUID, user: CurrentUser, db: DbSession) -> RunDetail:
    return run_detail(service.get_run(db, user=user, run_id=run_id))


def run_detail(run: AnalysisRun) -> RunDetail:
    return RunDetail(
        **run_summary(run).model_dump(),
        error_code=run.error_code,
        error_message=run.error_message,
        model=run.model,
        cancel_requested=run.cancel_requested,
        started_at=run.started_at,
        events=[ActivityEventOut.model_validate(event) for event in run.events],
        outcome=_outcome(run),
    )


@router.post(
    "/{run_id}/cancel",
    response_model=RunSummary,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Cancel a queued or running analysis",
)
def cancel_analysis(
    run_id: uuid.UUID, request: Request, user: CurrentUser, db: DbSession
) -> RunSummary:
    summary = run_summary(service.request_cancel(db, user=user, run_id=run_id))
    notifier: RunNotifier = request.app.state.run_notifier
    notifier.notify(run_id)
    return summary


# --- Live updates (Server-Sent Events) -------------------------------------------------------

STREAM_HEADERS = {
    # no-transform stops proxies (and Next.js's compression) from buffering the stream.
    "Cache-Control": "no-cache, no-transform",
    # nginx-style proxies buffer responses unless told not to.
    "X-Accel-Buffering": "no",
}

EndReason = Literal["session_ended", "not_found", "timeout", "too_many_streams"]


def _frame(event: str, data: str) -> str:
    # Compact JSON has no newlines, so one data line is enough.
    return f"event: {event}\ndata: {data}\n\n"


def _end(reason: EndReason) -> str:
    return _frame("end", json.dumps({"reason": reason}))


@router.get(
    "/{run_id}/events",
    summary="Live updates for an analysis (Server-Sent Events)",
    description=(
        "A `text/event-stream`. Each `run` event carries the full analysis (the same JSON as "
        "`GET /analyses/{run_id}`) whenever it changes, starting with its current state. The "
        "stream closes after a finished state, or with an `end` event whose `reason` is "
        "`session_ended`, `not_found`, `timeout` or `too_many_streams`; clients then fall "
        "back to polling `GET /analyses/{run_id}`."
    ),
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}, "description": "Event stream"}},
)
def stream_analysis(
    run_id: uuid.UUID,
    request: Request,
    user: CurrentUser,
    db: DbSession,
    settings: SettingsDep,
) -> StreamingResponse:
    service.get_run(db, user=user, run_id=run_id)  # 404 for other users' runs
    notifier: RunNotifier = request.app.state.run_notifier
    session_factory = request.app.state.session_factory
    token = request.cookies.get(settings.session_cookie_name, "")
    user_id = user.id

    def load() -> tuple[EndReason | None, RunDetail | None]:
        # Re-checked on every read: signing out (or the session expiring) ends the stream.
        with session_factory() as session:
            current = resolve_session(session, token=token, settings=settings)
            if current is None or current.id != user_id:
                return "session_ended", None
            run = session.scalar(
                select(AnalysisRun).where(AnalysisRun.id == run_id, AnalysisRun.user_id == user_id)
            )
            if run is None:
                return "not_found", None
            return None, run_detail(run)

    async def events() -> AsyncIterator[str]:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + settings.event_stream_max_seconds
        try:
            with notifier.reserve(user_id), notifier.subscribe(run_id) as changed:
                last_payload: str | None = None
                last_sent = loop.time()
                while True:
                    # Cleared before reading, so a change committed during the read wakes
                    # the next iteration instead of being lost.
                    changed.clear()
                    reason, detail = await anyio.to_thread.run_sync(load)
                    if reason is not None or detail is None:
                        yield _end(reason or "not_found")
                        return
                    payload = detail.model_dump_json()
                    if payload != last_payload:
                        yield _frame("run", payload)
                        last_payload, last_sent = payload, loop.time()
                    if detail.status not in service.ACTIVE_STATUSES:
                        return
                    remaining = deadline - loop.time()
                    if remaining <= 0:
                        yield _end("timeout")
                        return
                    with contextlib.suppress(TimeoutError):
                        await asyncio.wait_for(
                            changed.wait(),
                            timeout=min(settings.event_stream_check_seconds, remaining),
                        )
                    if loop.time() - last_sent >= settings.event_stream_keepalive_seconds:
                        yield ": keep-alive\n\n"
                        last_sent = loop.time()
        except RateLimitedError:
            yield _end("too_many_streams")

    return StreamingResponse(events(), media_type="text/event-stream", headers=STREAM_HEADERS)
