"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import health
from app.config import Settings, get_settings
from app.errors import register_error_handlers
from app.logging_config import configure_logging
from app.middleware import RequestContextMiddleware

API_PREFIX = "/api"
DOCS_URL = f"{API_PREFIX}/docs"
OPENAPI_URL = f"{API_PREFIX}/openapi.json"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        settings.storage_dir.mkdir(parents=True, exist_ok=True)
        yield

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description=(
            "Upload a dataset, inspect its profile, and ask natural-language questions answered "
            "by a bounded agent that runs validated analytical tools."
        ),
        lifespan=lifespan,
        docs_url=DOCS_URL if settings.enable_api_docs else None,
        redoc_url=None,
        openapi_url=OPENAPI_URL if settings.enable_api_docs else None,
    )
    app.state.settings = settings
    app.dependency_overrides[get_settings] = lambda: settings

    register_error_handlers(app)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "X-Requested-With"],
        expose_headers=["X-Request-ID"],
        max_age=600,
    )
    # Added last so it runs first: every response, including CORS and error responses,
    # gets a request id and security headers.
    app.add_middleware(RequestContextMiddleware, docs_paths=frozenset({DOCS_URL, OPENAPI_URL}))

    api = APIRouter(prefix=API_PREFIX)
    api.include_router(health.router)
    app.include_router(api)
    return app
