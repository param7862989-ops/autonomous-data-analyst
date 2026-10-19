from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import DOCS_URL, OPENAPI_URL, create_app
from tests.conftest import CSRF_HEADERS, make_settings


def test_security_headers_present(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Content-Security-Policy"].startswith("default-src 'none'")
    assert response.headers["Cache-Control"] == "no-store"
    assert len(response.headers["X-Request-ID"]) == 32


def test_request_ids_are_unique(client: TestClient) -> None:
    first = client.get("/api/health").headers["X-Request-ID"]
    second = client.get("/api/health").headers["X-Request-ID"]
    assert first != second


def test_docs_are_served_without_api_csp(client: TestClient) -> None:
    response = client.get("/api/docs")
    assert response.status_code == 200
    assert "Content-Security-Policy" not in response.headers


def test_api_docs_can_be_disabled(tmp_path: Path) -> None:
    # The production overlay sets ENABLE_API_DOCS=false.
    app = create_app(make_settings(tmp_path, enable_api_docs=False))
    with TestClient(app, raise_server_exceptions=False, headers=CSRF_HEADERS) as client:
        assert client.get(DOCS_URL).status_code == 404
        assert client.get(OPENAPI_URL).status_code == 404
        assert client.get("/api/health").status_code == 200


def test_cors_allows_configured_origin_only(client: TestClient) -> None:
    allowed = client.options(
        "/api/health",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"},
    )
    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert allowed.headers.get("access-control-allow-credentials") == "true"

    denied = client.options(
        "/api/health",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in denied.headers
