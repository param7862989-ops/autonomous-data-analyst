"""Server capabilities the frontend needs to know about."""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.api.deps import CurrentUser, SettingsDep
from app.schemas.analyses import ServerConfig

router = APIRouter(tags=["meta"])


@router.get("/config", response_model=ServerConfig, summary="Features available on this server")
def server_config(request: Request, _: CurrentUser, settings: SettingsDep) -> ServerConfig:
    override: str | None = request.app.state.provider_override
    enabled = settings.analysis_enabled or override is not None
    model = override or (settings.llm_model if settings.analysis_enabled else None)
    return ServerConfig(analysis_enabled=enabled, model=model)
