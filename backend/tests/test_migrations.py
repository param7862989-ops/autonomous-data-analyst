from __future__ import annotations

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine, inspect

from app.db.base import Base
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
