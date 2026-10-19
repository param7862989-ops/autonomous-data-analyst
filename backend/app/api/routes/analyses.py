"""Analysis runs: progress, results, cancellation and history."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.agent.schemas import AgentOutcome
from app.api.deps import CurrentUser, DbSession
from app.db.models import AnalysisRun
from app.schemas.analyses import (
    ActivityEventOut,
    HistoryItem,
    HistoryList,
    RunDetail,
    RunSummary,
)
from app.services import conversations as service

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
    run = service.get_run(db, user=user, run_id=run_id)
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
def cancel_analysis(run_id: uuid.UUID, user: CurrentUser, db: DbSession) -> RunSummary:
    return run_summary(service.request_cancel(db, user=user, run_id=run_id))
