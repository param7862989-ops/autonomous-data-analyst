"""ORM models for application metadata.

Uploaded analytical data is *not* stored here: datasets are Parquet files in private storage and
only their metadata and profile live in PostgreSQL.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    false,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Timestamps, UUIDPrimaryKey, utcnow


class User(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "users"
    __table_args__ = (
        # Emails are normalized to lowercase before storage; enforce it so the unique
        # constraint is case-insensitive in practice.
        CheckConstraint("email = lower(email)", name="email_lowercase"),
    )

    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))

    sessions: Mapped[list[UserSession]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    datasets: Mapped[list[Dataset]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )


class UserSession(UUIDPrimaryKey, Base):
    """A login session. Only the SHA-256 of the cookie token is stored."""

    __tablename__ = "sessions"
    __table_args__ = (Index("ix_sessions_user_id_expires_at", "user_id", "expires_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    last_used_at: Mapped[datetime] = mapped_column(default=utcnow)
    expires_at: Mapped[datetime]

    user: Mapped[User] = relationship(back_populates="sessions")


class Dataset(UUIDPrimaryKey, Timestamps, Base):
    """Metadata and profile of an uploaded dataset. The data itself is a Parquet file at
    ``storage_key`` in private storage."""

    __tablename__ = "datasets"
    __table_args__ = (
        Index("ix_datasets_user_id_created_at", "user_id", "created_at"),
        CheckConstraint("file_format IN ('csv', 'xlsx')", name="file_format"),
        CheckConstraint("row_count >= 0 AND column_count >= 0", name="non_negative_shape"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255))
    original_filename: Mapped[str] = mapped_column(String(255))
    file_format: Mapped[str] = mapped_column(String(8))
    sheet_name: Mapped[str | None] = mapped_column(String(255))
    upload_size_bytes: Mapped[int] = mapped_column(BigInteger)
    stored_size_bytes: Mapped[int] = mapped_column(BigInteger)
    row_count: Mapped[int]
    column_count: Mapped[int]
    storage_key: Mapped[str] = mapped_column(String(255), unique=True)
    # [{name, original_name, semantic_type, dtype}, ...] in column order.
    columns: Mapped[list[Any]]
    profile: Mapped[dict[str, Any]]

    user: Mapped[User] = relationship(back_populates="datasets")

    conversations: Mapped[list[Conversation]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan", passive_deletes=True
    )


class Conversation(UUIDPrimaryKey, Timestamps, Base):
    """A thread of questions about one dataset. Each turn is one AnalysisRun."""

    __tablename__ = "conversations"
    __table_args__ = (
        Index("ix_conversations_user_id_updated_at", "user_id", "updated_at"),
        Index("ix_conversations_dataset_id", "dataset_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    dataset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200))

    dataset: Mapped[Dataset] = relationship(back_populates="conversations")
    runs: Mapped[list[AnalysisRun]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="AnalysisRun.created_at",
    )


RUN_STATUSES = ("queued", "running", "completed", "failed", "cancelled")
ACTIVE_RUN_STATUSES = ("queued", "running")
# At most one active run per conversation, enforced by the database so that two simultaneous
# requests cannot both start one (the service checks first; this decides any race).
ONE_ACTIVE_RUN_INDEX = "uq_analysis_runs_conversation_id_active"


class AnalysisRun(UUIDPrimaryKey, Timestamps, Base):
    """One question and everything the agent produced for it."""

    __tablename__ = "analysis_runs"
    __table_args__ = (
        Index("ix_analysis_runs_user_id_created_at", "user_id", "created_at"),
        Index("ix_analysis_runs_conversation_id_created_at", "conversation_id", "created_at"),
        Index("ix_analysis_runs_status", "status"),
        Index(
            ONE_ACTIVE_RUN_INDEX,
            "conversation_id",
            unique=True,
            postgresql_where=text(f"status IN {ACTIVE_RUN_STATUSES}"),
        ),
        CheckConstraint(f"status IN {RUN_STATUSES}", name="status"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"))
    question: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="queued")
    stop_reason: Mapped[str | None] = mapped_column(String(32))
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(100))
    # AgentOutcome: plan, answer, results, charts, grounding report and token usage.
    outcome: Mapped[dict[str, Any] | None]
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]

    conversation: Mapped[Conversation] = relationship(back_populates="runs")
    events: Mapped[list[AnalysisEvent]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="AnalysisEvent.seq",
    )


class AnalysisEvent(Base):
    """A user-visible activity step of a run. Upserted by (run_id, key) as it progresses."""

    __tablename__ = "analysis_events"
    __table_args__ = (
        UniqueConstraint("run_id", "key", name="uq_analysis_events_run_id_key"),
        Index("ix_analysis_events_run_id_seq", "run_id", "seq"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("analysis_runs.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(64))
    seq: Mapped[int]
    kind: Mapped[str] = mapped_column(String(16))
    label: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(16))
    detail: Mapped[str | None] = mapped_column(Text)
    result_id: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    run: Mapped[AnalysisRun] = relationship(back_populates="events")
