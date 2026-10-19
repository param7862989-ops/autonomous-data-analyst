"""ORM models for application metadata.

Uploaded analytical data is *not* stored here: datasets are Parquet files in private storage and
only their metadata and profile live in PostgreSQL.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, String
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
