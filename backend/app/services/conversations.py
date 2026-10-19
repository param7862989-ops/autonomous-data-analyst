"""Conversation and analysis-run use cases (everything except executing a run).

All reads are scoped to the requesting user; another user's records are indistinguishable from
records that do not exist.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.agent.context import PriorTurn
from app.datasets.service import get_dataset
from app.db.base import utcnow
from app.db.models import AnalysisRun, Conversation, Dataset, User
from app.errors import ConflictError, NotFoundError

ACTIVE_STATUSES = ("queued", "running")
TERMINAL_STATUSES = ("completed", "failed", "cancelled")
TITLE_LENGTH = 80


def _title_from(question: str) -> str:
    text = " ".join(question.split())
    return text if len(text) <= TITLE_LENGTH else text[: TITLE_LENGTH - 1] + "…"


def create_conversation(
    db: Session, *, user: User, dataset_id: uuid.UUID, title: str | None
) -> Conversation:
    dataset = get_dataset(db, user=user, dataset_id=dataset_id)
    conversation = Conversation(
        user_id=user.id,
        dataset_id=dataset.id,
        title=(title or "").strip()[:200] or f"Analysis of {dataset.name}"[:200],
    )
    db.add(conversation)
    db.commit()
    return conversation


def get_conversation(db: Session, *, user: User, conversation_id: uuid.UUID) -> Conversation:
    conversation = db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id, Conversation.user_id == user.id
        )
    )
    if conversation is None:
        raise NotFoundError("Conversation not found.")
    return conversation


def list_conversations(
    db: Session, *, user: User, dataset_id: uuid.UUID | None, limit: int, offset: int
) -> tuple[list[tuple[Conversation, str, int]], int]:
    """(conversation, dataset name, run count) rows, newest activity first, and the total."""
    filters = [Conversation.user_id == user.id]
    if dataset_id is not None:
        filters.append(Conversation.dataset_id == dataset_id)
    total = db.scalar(select(func.count()).select_from(Conversation).where(*filters)) or 0
    run_counts = (
        select(AnalysisRun.conversation_id, func.count().label("runs"))
        .group_by(AnalysisRun.conversation_id)
        .subquery()
    )
    rows = db.execute(
        select(Conversation, Dataset.name, func.coalesce(run_counts.c.runs, 0))
        .join(Dataset, Dataset.id == Conversation.dataset_id)
        .outerjoin(run_counts, run_counts.c.conversation_id == Conversation.id)
        .where(*filters)
        .order_by(Conversation.updated_at.desc(), Conversation.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return [(row[0], row[1], int(row[2])) for row in rows], int(total)


def rename_conversation(
    db: Session, *, user: User, conversation_id: uuid.UUID, title: str
) -> Conversation:
    conversation = get_conversation(db, user=user, conversation_id=conversation_id)
    conversation.title = title.strip()[:200] or conversation.title
    db.commit()
    return conversation


def delete_conversation(db: Session, *, user: User, conversation_id: uuid.UUID) -> None:
    conversation = get_conversation(db, user=user, conversation_id=conversation_id)
    # Running analyses notice the cancellation flag; their rows disappear with the cascade.
    db.execute(
        update(AnalysisRun)
        .where(
            AnalysisRun.conversation_id == conversation.id,
            AnalysisRun.status.in_(ACTIVE_STATUSES),
        )
        .values(cancel_requested=True)
    )
    db.delete(conversation)
    db.commit()


def start_run(db: Session, *, user: User, conversation_id: uuid.UUID, question: str) -> AnalysisRun:
    conversation = get_conversation(db, user=user, conversation_id=conversation_id)
    active = db.scalar(
        select(func.count())
        .select_from(AnalysisRun)
        .where(
            AnalysisRun.conversation_id == conversation.id,
            AnalysisRun.status.in_(ACTIVE_STATUSES),
        )
    )
    if active:
        raise ConflictError(
            "An analysis is already running in this conversation. Wait for it to finish or "
            "cancel it.",
            code="analysis_in_progress",
        )
    is_first = not db.scalar(
        select(func.count())
        .select_from(AnalysisRun)
        .where(AnalysisRun.conversation_id == conversation.id)
    )
    run = AnalysisRun(
        user_id=user.id,
        conversation_id=conversation.id,
        dataset_id=conversation.dataset_id,
        question=question.strip(),
        status="queued",
    )
    db.add(run)
    if is_first and conversation.title.startswith("Analysis of "):
        conversation.title = _title_from(question)
    conversation.updated_at = utcnow()
    db.commit()
    return run


def get_run(db: Session, *, user: User, run_id: uuid.UUID) -> AnalysisRun:
    run = db.scalar(
        select(AnalysisRun).where(AnalysisRun.id == run_id, AnalysisRun.user_id == user.id)
    )
    if run is None:
        raise NotFoundError("Analysis not found.")
    return run


def list_runs(
    db: Session,
    *,
    user: User,
    dataset_id: uuid.UUID | None,
    conversation_id: uuid.UUID | None,
    limit: int,
    offset: int,
) -> tuple[list[tuple[AnalysisRun, str]], int]:
    filters = [AnalysisRun.user_id == user.id]
    if dataset_id is not None:
        filters.append(AnalysisRun.dataset_id == dataset_id)
    if conversation_id is not None:
        filters.append(AnalysisRun.conversation_id == conversation_id)
    total = db.scalar(select(func.count()).select_from(AnalysisRun).where(*filters)) or 0
    rows = db.execute(
        select(AnalysisRun, Dataset.name)
        .join(Dataset, Dataset.id == AnalysisRun.dataset_id)
        .where(*filters)
        .order_by(AnalysisRun.created_at.desc(), AnalysisRun.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return [(row[0], row[1]) for row in rows], int(total)


def request_cancel(db: Session, *, user: User, run_id: uuid.UUID) -> AnalysisRun:
    run = get_run(db, user=user, run_id=run_id)
    if run.status in ACTIVE_STATUSES:
        # The flag covers the race where a worker picks the run up at the same moment: the
        # running agent checks it before every step.
        run.cancel_requested = True
    if run.status == "queued":
        run.status = "cancelled"
        run.stop_reason = "cancelled"
        run.finished_at = utcnow()
    db.commit()
    return run


def prior_turns(db: Session, run: AnalysisRun, limit: int = 5) -> list[PriorTurn]:
    """Earlier finished turns of the same conversation (same user and dataset), oldest first."""
    earlier = db.scalars(
        select(AnalysisRun)
        .where(
            AnalysisRun.conversation_id == run.conversation_id,
            AnalysisRun.user_id == run.user_id,
            AnalysisRun.created_at < run.created_at,
            AnalysisRun.status.in_(TERMINAL_STATUSES),
        )
        .order_by(AnalysisRun.created_at.desc())
        .limit(limit)
    ).all()
    return [
        PriorTurn.from_outcome(previous.question, previous.status, previous.outcome)
        for previous in reversed(earlier)
    ]
