"""Account and session use cases. No HTTP concerns here."""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.passwords import (
    burn_verification_time,
    hash_password,
    needs_rehash,
    verify_password,
)
from app.config import Settings
from app.db.base import utcnow
from app.db.models import User, UserSession
from app.errors import ConflictError

# Refresh ``last_used_at`` at most this often, to avoid a write on every request.
_TOUCH_INTERVAL = timedelta(minutes=5)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def register_user(db: Session, *, email: str, password: str) -> User:
    user = User(email=normalize_email(email), password_hash=hash_password(password))
    db.add(user)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(
            "An account with this email already exists.", code="email_taken"
        ) from exc
    return user


def authenticate(db: Session, *, email: str, password: str) -> User | None:
    user = db.scalar(select(User).where(User.email == normalize_email(email)))
    if user is None:
        burn_verification_time(password)
        return None
    if not verify_password(user.password_hash, password):
        return None
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    return user


def create_session(db: Session, *, user: User, settings: Settings) -> str:
    """Create a session and return the raw token (only its hash is stored)."""
    now = utcnow()
    # Opportunistic cleanup of this user's expired sessions.
    db.execute(
        delete(UserSession).where(UserSession.user_id == user.id, UserSession.expires_at <= now)
    )
    token = secrets.token_urlsafe(32)
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=hash_token(token),
            created_at=now,
            last_used_at=now,
            expires_at=now + timedelta(hours=settings.session_ttl_hours),
        )
    )
    return token


def resolve_session(db: Session, *, token: str, settings: Settings) -> User | None:
    """Return the user for a valid, unexpired, recently used session token."""
    now = utcnow()
    session = db.scalar(select(UserSession).where(UserSession.token_hash == hash_token(token)))
    if session is None:
        return None
    idle_limit = timedelta(hours=settings.session_idle_timeout_hours)
    if session.expires_at <= now or session.last_used_at <= now - idle_limit:
        db.delete(session)
        db.commit()
        return None
    if now - session.last_used_at >= _TOUCH_INTERVAL:
        session.last_used_at = now
        db.commit()
    return session.user


def revoke_session(db: Session, *, token: str) -> None:
    db.execute(delete(UserSession).where(UserSession.token_hash == hash_token(token)))
