from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_liveness(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_ok(client: TestClient) -> None:
    response = client.get("/api/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert {"name": "storage", "ok": True} in body["checks"]


def test_readiness_reports_unwritable_storage(tmp_path: Path) -> None:
    # A regular file where the storage directory should be makes mkdir fail.
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        environment="test",
        storage_dir=blocker / "storage",
    )
    app = create_app(settings)
    # Lifespan would fail creating the directory, so call without running startup.
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/api/health/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    # No filesystem path leaks into the response.
    assert str(tmp_path) not in response.text
