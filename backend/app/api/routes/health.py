"""Liveness and readiness endpoints."""

from __future__ import annotations

import logging
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/health", tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"]


class ReadinessCheck(BaseModel):
    name: str
    ok: bool


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: list[ReadinessCheck]


@router.get("", response_model=HealthResponse, summary="Liveness probe")
def health() -> HealthResponse:
    """Returns 200 while the process is serving requests. Does not touch dependencies."""
    return HealthResponse(status="ok")


def _check_storage(settings: Settings) -> bool:
    try:
        settings.storage_dir.mkdir(parents=True, exist_ok=True)
        probe = settings.storage_dir / f".probe-{uuid.uuid4().hex}"
        probe.write_bytes(b"ok")
        probe.unlink()
        return True
    except OSError:
        logger.warning("Readiness: storage directory is not writable")
        return False


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    summary="Readiness probe",
    responses={503: {"model": ReadinessResponse}},
)
def ready(settings: Annotated[Settings, Depends(get_settings)]) -> JSONResponse:
    """Checks the dependencies required to serve traffic. Returns 503 if any check fails."""
    checks = [ReadinessCheck(name="storage", ok=_check_storage(settings))]
    all_ok = all(check.ok for check in checks)
    body = ReadinessResponse(status="ready" if all_ok else "not_ready", checks=checks)
    return JSONResponse(status_code=200 if all_ok else 503, content=body.model_dump())
