from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine, inspect, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import AnalysisRun, Conversation, Dataset, User
from tests.conftest import alembic_config, require_database


def test_upgrade_downgrade_roundtrip(migrated_engine: Engine) -> None:
    config = alembic_config(require_database())
    command.downgrade(config, "base")
    assert set(inspect(migrated_engine).get_table_names()) <= {"alembic_version"}
    command.upgrade(config, "head")
    tables = set(inspect(migrated_engine).get_table_names())
    assert {"users", "sessions"} <= tables


def test_models_match_migrations(migrated_engine: Engine) -> None:
    with migrated_engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        diff = compare_metadata(context, Base.metadata)
    assert diff == [], f"Models and migrations differ; run alembic revision --autogenerate: {diff}"


def test_one_active_run_migration_resolves_existing_duplicates(db_engine: Engine) -> None:
    # Before 0004 two active runs could exist in one conversation; upgrading keeps the newest
    # active and fails the others, as restart recovery would, so the unique index can be built.
    config = alembic_config(require_database())
    command.downgrade(config, "0003")
    try:
        user_id, dataset_id, conversation_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        start = datetime(2026, 1, 1, tzinfo=UTC)
        with Session(db_engine) as db:
            db.add(User(id=user_id, email="migration@example.com", password_hash="x"))
            db.flush()
            db.add(
                Dataset(
                    id=dataset_id,
                    user_id=user_id,
                    name="d",
                    original_filename="d.csv",
                    file_format="csv",
                    upload_size_bytes=1,
                    stored_size_bytes=1,
                    row_count=1,
                    column_count=1,
                    storage_key="migration-test",
                    columns=[],
                    profile={},
                )
            )
            db.flush()
            db.add(
                Conversation(id=conversation_id, user_id=user_id, dataset_id=dataset_id, title="t")
            )
            db.flush()
            for minute, (question, status) in enumerate(
                [("older active", "running"), ("newest active", "queued"), ("done", "completed")]
            ):
                db.add(
                    AnalysisRun(
                        user_id=user_id,
                        conversation_id=conversation_id,
                        dataset_id=dataset_id,
                        question=question,
                        status=status,
                        created_at=start + timedelta(minutes=minute),
                    )
                )
            db.commit()
        command.upgrade(config, "head")
        with Session(db_engine) as db:
            rows = db.execute(
                select(AnalysisRun.question, AnalysisRun.status, AnalysisRun.error_code)
            )
            result = {question: (status, code) for question, status, code in rows}
        assert result == {
            "older active": ("failed", "interrupted"),
            "newest active": ("queued", None),
            "done": ("completed", None),
        }
    finally:
        command.upgrade(config, "head")
