"""Shared FastAPI dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.auth.rate_limit import RateLimiter
from app.auth.service import resolve_session
from app.config import Settings, get_settings
from app.db.models import User
from app.db.session import get_db
from app.errors import AuthenticationError

DbSession = Annotated[Session, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_rate_limiter(request: Request) -> RateLimiter:
    limiter: RateLimiter = request.app.state.rate_limiter
    return limiter


RateLimiterDep = Annotated[RateLimiter, Depends(get_rate_limiter)]


def client_ip(request: Request) -> str:
    # Behind a reverse proxy, uvicorn's --proxy-headers/--forwarded-allow-ips rewrites
    # request.client from X-Forwarded-For, but only for trusted proxy addresses.
    return request.client.host if request.client else "unknown"


def get_current_user(request: Request, db: DbSession, settings: SettingsDep) -> User:
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise AuthenticationError("Sign in to continue.")
    user = resolve_session(db, token=token, settings=settings)
    if user is None:
        raise AuthenticationError("Your session has ended. Sign in again.", code="session_expired")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
