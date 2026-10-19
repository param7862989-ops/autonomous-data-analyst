"""Conversations: threads of questions about one dataset."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Request, Response, status

from app.api.deps import CurrentUser, DbSession, RateLimiterDep, SettingsDep
from app.api.routes.analyses import run_summary
from app.db.models import AnalysisRun, Conversation
from app.errors import ServiceUnavailableError
from app.schemas.analyses import (
    AnalysisCreate,
    ConversationCreate,
    ConversationDetail,
    ConversationList,
    ConversationSummary,
    ConversationUpdate,
    RunSummary,
)
from app.services import conversations as service
from app.services.runner import AnalysisRunner

router = APIRouter(prefix="/conversations", tags=["conversations"])


def _summary(conversation: Conversation, dataset_name: str, run_count: int) -> ConversationSummary:
    return ConversationSummary(
        id=conversation.id,
        dataset_id=conversation.dataset_id,
        dataset_name=dataset_name,
        title=conversation.title,
        run_count=run_count,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


def _detail(conversation: Conversation) -> ConversationDetail:
    runs: list[AnalysisRun] = list(conversation.runs)
    return ConversationDetail(
        **_summary(conversation, conversation.dataset.name, len(runs)).model_dump(),
        runs=[run_summary(run) for run in runs],
    )


@router.post(
    "",
    response_model=ConversationDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Start a conversation about a dataset",
)
def create_conversation(
    body: ConversationCreate, user: CurrentUser, db: DbSession
) -> ConversationDetail:
    conversation = service.create_conversation(
        db, user=user, dataset_id=body.dataset_id, title=body.title
    )
    return _detail(conversation)


@router.get("", response_model=ConversationList, summary="List your conversations")
def list_conversations(
    user: CurrentUser,
    db: DbSession,
    dataset_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ConversationList:
    rows, total = service.list_conversations(
        db, user=user, dataset_id=dataset_id, limit=limit, offset=offset
    )
    return ConversationList(
        items=[_summary(c, name, count) for c, name, count in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{conversation_id}",
    response_model=ConversationDetail,
    summary="A conversation and its questions",
)
def get_conversation(
    conversation_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> ConversationDetail:
    return _detail(service.get_conversation(db, user=user, conversation_id=conversation_id))


@router.patch("/{conversation_id}", response_model=ConversationDetail, summary="Rename")
def rename_conversation(
    conversation_id: uuid.UUID, body: ConversationUpdate, user: CurrentUser, db: DbSession
) -> ConversationDetail:
    conversation = service.rename_conversation(
        db, user=user, conversation_id=conversation_id, title=body.title
    )
    return _detail(conversation)


@router.delete(
    "/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a conversation and its analyses",
)
def delete_conversation(conversation_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Response:
    service.delete_conversation(db, user=user, conversation_id=conversation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{conversation_id}/analyses",
    response_model=RunSummary,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ask a question (starts an analysis)",
    description=(
        "Queues an analysis and returns immediately. Poll `GET /api/analyses/{id}` for "
        "progress events and the result. Earlier questions in the same conversation are used "
        "as context for follow-ups."
    ),
)
def start_analysis(
    conversation_id: uuid.UUID,
    body: AnalysisCreate,
    request: Request,
    user: CurrentUser,
    db: DbSession,
    settings: SettingsDep,
    limiter: RateLimiterDep,
) -> RunSummary:
    if not settings.analysis_enabled and not request.app.state.provider_override:
        raise ServiceUnavailableError(
            "Analysis is unavailable: no language model is configured on this server.",
            code="llm_not_configured",
        )
    limiter.hit(
        "analysis:user",
        str(user.id),
        limit=settings.analyses_per_user_per_hour,
        window_seconds=3600,
    )
    run = service.start_run(db, user=user, conversation_id=conversation_id, question=body.question)
    runner: AnalysisRunner = request.app.state.runner
    runner.submit(run.id)
    db.refresh(run)
    return run_summary(run)
