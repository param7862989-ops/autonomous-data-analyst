from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import make_settings

BODY = {"email": "ana@example.com", "password": "correct horse battery"}


@pytest.fixture
def bare_client(tmp_path: Path) -> TestClient:
    # No default CSRF header and no database: rejection happens before any handler runs.
    return TestClient(create_app(make_settings(tmp_path)), raise_server_exceptions=False)


def test_unsafe_request_without_header_is_rejected(bare_client: TestClient) -> None:
    response = bare_client.post("/api/auth/login", json=BODY)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_failed"
    assert response.headers["X-Request-ID"]


def test_wrong_header_value_is_rejected(bare_client: TestClient) -> None:
    response = bare_client.post(
        "/api/auth/login", json=BODY, headers={"X-Requested-With": "XMLHttpRequest"}
    )
    assert response.status_code == 403


def test_foreign_origin_is_rejected(bare_client: TestClient) -> None:
    response = bare_client.post(
        "/api/auth/logout",
        headers={"X-Requested-With": "fetch", "Origin": "https://evil.example"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["details"]["reason"] == "origin_not_allowed"


def test_cross_site_fetch_metadata_is_rejected(bare_client: TestClient) -> None:
    response = bare_client.post(
        "/api/auth/logout",
        headers={"X-Requested-With": "fetch", "Sec-Fetch-Site": "cross-site"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["details"]["reason"] == "cross_site"


def test_safe_methods_do_not_need_the_header(bare_client: TestClient) -> None:
    assert bare_client.get("/api/health").status_code == 200
