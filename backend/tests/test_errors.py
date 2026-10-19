from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.errors import NotFoundError, RateLimitedError


class _Payload(BaseModel):
    name: str
    count: int


def _add_test_routes(app: FastAPI) -> None:
    @app.get("/api/_test/boom")
    def boom() -> None:
        raise RuntimeError("secret internal detail /etc/passwd DATABASE_URL=postgres://x")

    @app.get("/api/_test/missing")
    def missing() -> None:
        raise NotFoundError("Dataset not found.")

    @app.get("/api/_test/limited")
    def limited() -> None:
        raise RateLimitedError("Too many requests.", details={"retry_after": 30})

    @app.post("/api/_test/validate")
    def validate(payload: _Payload) -> dict[str, str]:
        return {"name": payload.name}


def test_unhandled_exception_is_sanitized(app: FastAPI, client: TestClient) -> None:
    _add_test_routes(app)
    response = client.get("/api/_test/boom")
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    assert body["error"]["message"] == "An unexpected error occurred."
    assert body["error"]["request_id"] == response.headers["X-Request-ID"]
    assert "secret" not in response.text
    assert "DATABASE_URL" not in response.text
    assert "Traceback" not in response.text


def test_app_error_envelope(app: FastAPI, client: TestClient) -> None:
    _add_test_routes(app)
    response = client.get("/api/_test/missing")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert response.json()["error"]["message"] == "Dataset not found."


def test_rate_limit_sets_retry_after(app: FastAPI, client: TestClient) -> None:
    _add_test_routes(app)
    response = client.get("/api/_test/limited")
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "30"


def test_validation_error_does_not_echo_input(app: FastAPI, client: TestClient) -> None:
    _add_test_routes(app)
    response = client.post(
        "/api/_test/validate", json={"name": "hunter2-super-secret", "count": "not-a-number"}
    )
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["details"][0]["loc"] == ["body", "count"]
    assert "hunter2-super-secret" not in response.text
    assert "not-a-number" not in response.text


def test_unknown_route_uses_envelope(client: TestClient) -> None:
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_method_not_allowed_uses_envelope(client: TestClient) -> None:
    response = client.delete("/api/health")
    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"
