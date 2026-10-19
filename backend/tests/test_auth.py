from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from app.auth.service import hash_token
from app.db.base import utcnow
from app.db.models import User, UserSession
from app.main import create_app
from tests.conftest import CSRF_HEADERS, make_settings, new_client, register

PASSWORD = "correct horse battery"


def session_cookie(client: TestClient) -> str:
    token = client.cookies.get("ada_session")
    assert token
    return token


def test_register_sets_secure_session_cookie(db_client: TestClient) -> None:
    response = db_client.post(
        "/api/auth/register", json={"email": "Ana@Example.com", "password": PASSWORD}
    )
    assert response.status_code == 201
    assert response.json()["email"] == "ana@example.com"
    cookie_header = response.headers["set-cookie"].lower()
    assert "httponly" in cookie_header
    assert "samesite=lax" in cookie_header
    assert "path=/" in cookie_header
    assert "max-age=" in cookie_header

    me = db_client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "ana@example.com"


def test_passwords_and_tokens_are_stored_hashed(db_client: TestClient, db_engine: Engine) -> None:
    register(db_client)
    token = session_cookie(db_client)
    with Session(db_engine) as db:
        user = db.scalars(select(User)).one()
        stored = db.scalars(select(UserSession)).one()
    assert user.password_hash.startswith("$argon2id$")
    assert PASSWORD not in user.password_hash
    assert stored.token_hash == hash_token(token)
    assert stored.token_hash != token


def test_duplicate_email_is_rejected_case_insensitively(db_client: TestClient) -> None:
    register(db_client, email="ana@example.com")
    response = new_client(db_client.app).post(
        "/api/auth/register", json={"email": "ANA@example.com", "password": PASSWORD}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "email_taken"


@pytest.mark.parametrize(
    ("email", "password"),
    [
        ("ana@example.com", "tiny-pw9"),
        ("ana@example.com", "x" * 129),
        ("ana@example.com", "          "),
        ("ana@example.com", "ANA@example.com"),
        ("not-an-email", PASSWORD),
    ],
)
def test_registration_validation(db_client: TestClient, email: str, password: str) -> None:
    response = db_client.post("/api/auth/register", json={"email": email, "password": password})
    assert response.status_code == 422
    if password.strip():
        assert password not in response.text


def test_registration_can_be_disabled(db_engine: Engine, tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path, allow_registration=False))
    with TestClient(app, headers=CSRF_HEADERS) as client:
        response = client.post(
            "/api/auth/register", json={"email": "ana@example.com", "password": PASSWORD}
        )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "registration_disabled"


def test_login_success_and_failures_share_a_message(db_client: TestClient) -> None:
    register(db_client)
    client = new_client(db_client.app)

    wrong_password = client.post(
        "/api/auth/login", json={"email": "ana@example.com", "password": "wrong password!"}
    )
    unknown_email = client.post(
        "/api/auth/login", json={"email": "nobody@example.com", "password": PASSWORD}
    )
    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json()["error"]["message"] == unknown_email.json()["error"]["message"]
    assert "set-cookie" not in wrong_password.headers

    ok = client.post("/api/auth/login", json={"email": "ANA@example.com", "password": PASSWORD})
    assert ok.status_code == 200
    assert client.get("/api/auth/me").status_code == 200


def test_login_rotates_existing_session(db_client: TestClient) -> None:
    register(db_client)
    old_token = session_cookie(db_client)
    db_client.post("/api/auth/login", json={"email": "ana@example.com", "password": PASSWORD})
    new_token = session_cookie(db_client)
    assert new_token != old_token

    stale = new_client(db_client.app)
    stale.cookies.set("ada_session", old_token)
    assert stale.get("/api/auth/me").status_code == 401


def test_logout_revokes_session_server_side(db_client: TestClient) -> None:
    register(db_client)
    token = session_cookie(db_client)
    response = db_client.post("/api/auth/logout")
    assert response.status_code == 204
    assert "max-age=0" in response.headers["set-cookie"].lower()
    assert db_client.get("/api/auth/me").status_code == 401

    # Replaying the old cookie does not work either.
    replay = new_client(db_client.app)
    replay.cookies.set("ada_session", token)
    assert replay.get("/api/auth/me").status_code == 401


def test_logout_without_session_is_harmless(db_client: TestClient) -> None:
    assert db_client.post("/api/auth/logout").status_code == 204


def test_me_requires_authentication(db_client: TestClient) -> None:
    response = db_client.get("/api/auth/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"


def test_forged_token_is_rejected(db_client: TestClient) -> None:
    db_client.cookies.set("ada_session", "forged-token-value")
    response = db_client.get("/api/auth/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "session_expired"


def test_expired_session_is_rejected_and_deleted(db_client: TestClient, db_engine: Engine) -> None:
    register(db_client)
    with Session(db_engine) as db:
        db.execute(update(UserSession).values(expires_at=utcnow() - timedelta(seconds=1)))
        db.commit()
    assert db_client.get("/api/auth/me").status_code == 401
    with Session(db_engine) as db:
        assert db.scalars(select(UserSession)).all() == []


def test_idle_session_is_rejected(db_client: TestClient, db_engine: Engine) -> None:
    register(db_client)
    with Session(db_engine) as db:
        db.execute(update(UserSession).values(last_used_at=utcnow() - timedelta(hours=25)))
        db.commit()
    assert db_client.get("/api/auth/me").status_code == 401


def test_activity_extends_idle_window(db_client: TestClient, db_engine: Engine) -> None:
    register(db_client)
    stale_time = utcnow() - timedelta(hours=1)
    with Session(db_engine) as db:
        db.execute(update(UserSession).values(last_used_at=stale_time))
        db.commit()
    assert db_client.get("/api/auth/me").status_code == 200
    with Session(db_engine) as db:
        assert db.scalars(select(UserSession)).one().last_used_at > stale_time


def test_production_cookies_are_secure(db_engine: Engine, tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path, environment="production"))
    with TestClient(app, headers=CSRF_HEADERS, base_url="https://testserver") as client:
        response = client.post(
            "/api/auth/register", json={"email": "ana@example.com", "password": PASSWORD}
        )
    assert response.status_code == 201
    assert "secure" in response.headers["set-cookie"].lower()


def test_login_rate_limited_per_ip(db_engine: Engine, tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path, login_attempts_per_ip_per_minute=3))
    with TestClient(app, headers=CSRF_HEADERS) as client:
        statuses = [
            client.post(
                "/api/auth/login", json={"email": f"u{i}@example.com", "password": "nope-nope"}
            ).status_code
            for i in range(4)
        ]
        assert statuses == [401, 401, 401, 429]
        limited = client.post(
            "/api/auth/login", json={"email": "x@example.com", "password": "nope-nope"}
        )
    assert limited.json()["error"]["code"] == "rate_limited"
    assert int(limited.headers["Retry-After"]) >= 1


def test_login_failures_rate_limited_per_account(db_engine: Engine, tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path, login_attempts_per_account_per_15_minutes=2))
    with TestClient(app, headers=CSRF_HEADERS) as client:
        register(client)
        attempts = [
            client.post(
                "/api/auth/login", json={"email": "ana@example.com", "password": "wrong-guess"}
            ).status_code
            for _ in range(3)
        ]
        assert attempts == [401, 401, 429]
        # Even the right password is refused while the account is throttled.
        blocked = client.post(
            "/api/auth/login", json={"email": "ana@example.com", "password": PASSWORD}
        )
        assert blocked.status_code == 429
