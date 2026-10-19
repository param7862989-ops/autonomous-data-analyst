"""Engine and session management.

Sessions are synchronous: request handlers that touch the database are plain ``def`` functions,
which FastAPI runs in its thread pool.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

from fastapi import Request
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings

logger = logging.getLogger(__name__)


def create_db_engine(settings: Settings) -> Engine:
    return create_engine(
        settings.database_url,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_pool_size,
        pool_pre_ping=True,
        pool_recycle=1800,
        connect_args={
            "connect_timeout": 5,
            "options": f"-c statement_timeout={settings.database_statement_timeout_ms}",
        },
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def get_db(request: Request) -> Iterator[Session]:
    """Request-scoped session. Rolled back automatically if the handler raises."""
    factory: sessionmaker[Session] = request.app.state.session_factory
    with factory() as session:
        yield session


def database_is_reachable(engine: Engine) -> bool:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # noqa: BLE001 - any failure means "not ready"
        # Log only the type: driver messages can include hostnames and user names.
        logger.warning("Database readiness check failed: %s", type(exc).__name__)
        return False
