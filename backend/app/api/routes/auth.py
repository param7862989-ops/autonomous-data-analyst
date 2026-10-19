"""Registration, login, logout and the current user."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from app.api.deps import (
    CurrentUser,
    DbSession,
    RateLimiterDep,
    SettingsDep,
    client_ip,
)
from app.auth import service
from app.config import Settings
from app.errors import AuthenticationError, PermissionDeniedError
from app.schemas.auth import LoginRequest, RegisterRequest, UserResponse

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/",
    )


def _clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        key=settings.session_cookie_name,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/",
    )


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an account and sign in",
)
def register(
    body: RegisterRequest,
    request: Request,
    response: Response,
    db: DbSession,
    settings: SettingsDep,
    limiter: RateLimiterDep,
) -> UserResponse:
    if not settings.allow_registration:
        raise PermissionDeniedError(
            "Registration is closed on this server.", code="registration_disabled"
        )
    limiter.hit(
        "register:ip",
        client_ip(request),
        limit=settings.registrations_per_ip_per_hour,
        window_seconds=3600,
    )
    user = service.register_user(db, email=body.email, password=body.password)
    token = service.create_session(db, user=user, settings=settings)
    db.commit()
    _set_session_cookie(response, token, settings)
    return UserResponse.model_validate(user)


@router.post("/login", response_model=UserResponse, summary="Sign in")
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: DbSession,
    settings: SettingsDep,
    limiter: RateLimiterDep,
) -> UserResponse:
    account_key = service.normalize_email(body.email)
    limiter.hit(
        "login:ip",
        client_ip(request),
        limit=settings.login_attempts_per_ip_per_minute,
        window_seconds=60,
    )
    # Only failures count against the account, so a legitimate user is never locked out by
    # their own successful sign-ins.
    limiter.check(
        "login:account",
        account_key,
        limit=settings.login_attempts_per_account_per_15_minutes,
        window_seconds=900,
    )
    user = service.authenticate(db, email=body.email, password=body.password)
    if user is None:
        limiter.record("login:account", account_key, window_seconds=900)
        raise AuthenticationError("Incorrect email or password.", code="invalid_credentials")

    # Rotate: a pre-existing session cookie on this browser is revoked (prevents fixation).
    previous = request.cookies.get(settings.session_cookie_name)
    if previous:
        service.revoke_session(db, token=previous)
    token = service.create_session(db, user=user, settings=settings)
    db.commit()
    _set_session_cookie(response, token, settings)
    return UserResponse.model_validate(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Sign out")
def logout(request: Request, db: DbSession, settings: SettingsDep) -> Response:
    token = request.cookies.get(settings.session_cookie_name)
    if token:
        service.revoke_session(db, token=token)
        db.commit()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_session_cookie(response, settings)
    return response


@router.get("/me", response_model=UserResponse, summary="The signed-in user")
def me(user: CurrentUser) -> UserResponse:
    return UserResponse.model_validate(user)
