from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import UNREACHABLE_DATABASE_URL, make_settings


def test_liveness(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_ok(db_client: TestClient) -> None:
    response = db_client.get("/api/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert {"name": "database", "ok": True} in body["checks"]
    assert {"name": "storage", "ok": True} in body["checks"]


def test_readiness_reports_unreachable_database(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path, database_url=UNREACHABLE_DATABASE_URL))
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/health/ready")
    assert response.status_code == 503
    assert {"name": "database", "ok": False} in response.json()["checks"]
    assert "nobody" not in response.text  # no connection details leak


def test_readiness_reports_unwritable_storage(tmp_path: Path) -> None:
    # A regular file where the storage directory should be makes mkdir fail.
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")
    app = create_app(make_settings(tmp_path, storage_dir=blocker / "storage"))
    # Lifespan would fail creating the directory, so call without running startup.
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/api/health/ready")
    assert response.status_code == 503
    assert {"name": "storage", "ok": False} in response.json()["checks"]
    assert str(tmp_path) not in response.text
