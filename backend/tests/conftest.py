"""Shared fixtures.

Database tests run against a real PostgreSQL database named by ``TEST_DATABASE_URL``. The schema
is created with the Alembic migrations (never ``create_all``) once per session, and every table
is truncated after each test. Without ``TEST_DATABASE_URL`` those tests are skipped, unless
``REQUIRE_DB_TESTS=1`` (set in CI), in which case they fail.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text

from app.analytics.engine import AnalyticsEngine, EngineLimits
from app.analytics.operations import DatasetSchema
from app.config import Settings
from app.db.base import Base
from app.main import create_app
from tests.factories import SAMPLE_SALES, load_dataset

BACKEND_DIR = Path(__file__).resolve().parents[1]
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
# Valid syntax, guaranteed-unreachable port: for tests that must not touch a database.
UNREACHABLE_DATABASE_URL = "postgresql+psycopg://nobody@127.0.0.1:9/none"

CSRF_HEADERS = {"X-Requested-With": "fetch"}


def alembic_config(database_url: str) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    config.attributes["database_url"] = database_url
    config.attributes["configure_logger"] = False
    return config


def require_database() -> str:
    if TEST_DATABASE_URL:
        return TEST_DATABASE_URL
    if os.environ.get("REQUIRE_DB_TESTS") == "1":
        pytest.fail("REQUIRE_DB_TESTS=1 but TEST_DATABASE_URL is not set")
    pytest.skip("TEST_DATABASE_URL is not set")


@pytest.fixture(scope="session")
def migrated_engine() -> Iterator[Engine]:
    url = require_database()
    config = alembic_config(url)
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    engine = create_engine(url)
    yield engine
    engine.dispose()


def truncate_all(engine: Engine) -> None:
    tables = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
    if tables:
        with engine.begin() as connection:
            connection.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture
def db_engine(migrated_engine: Engine) -> Iterator[Engine]:
    yield migrated_engine
    truncate_all(migrated_engine)


def make_settings(tmp_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "test",
        "storage_dir": tmp_path / "storage",
        "allowed_origins": ["http://localhost:3000"],
        "database_url": TEST_DATABASE_URL or UNREACHABLE_DATABASE_URL,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg, arg-type]


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path)


@pytest.fixture
def settings_storage(settings: Settings) -> Path:
    return settings.storage_dir


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    """A client for endpoints that do not need the database."""
    with TestClient(app, raise_server_exceptions=False, headers=CSRF_HEADERS) as test_client:
        yield test_client


@pytest.fixture
def db_client(db_engine: Engine, app: FastAPI) -> Iterator[TestClient]:
    """A client backed by the migrated test database (cleaned after each test)."""
    with TestClient(app, raise_server_exceptions=False, headers=CSRF_HEADERS) as test_client:
        yield test_client


def new_client(app: FastAPI) -> TestClient:
    """An extra client with its own cookie jar (a second browser / user)."""
    return TestClient(app, raise_server_exceptions=False, headers=CSRF_HEADERS)


def register(
    client: TestClient, email: str = "ana@example.com", password: str = "correct horse battery"
) -> dict[str, object]:
    response = client.post("/api/auth/register", json={"email": email, "password": password})
    assert response.status_code == 201, response.text
    body: dict[str, object] = response.json()
    return body


@pytest.fixture(scope="session")
def sales_dataset(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, DatasetSchema]:
    return load_dataset(SAMPLE_SALES.read_bytes(), tmp_path_factory.mktemp("sales"))


@pytest.fixture
def sales_engine(sales_dataset: tuple[Path, DatasetSchema]) -> Iterator[AnalyticsEngine]:
    path, _ = sales_dataset
    with AnalyticsEngine(path, EngineLimits(query_timeout_seconds=10, max_result_rows=1000)) as e:
        yield e


@pytest.fixture
def sales_schema(sales_dataset: tuple[Path, DatasetSchema]) -> DatasetSchema:
    return sales_dataset[1]
