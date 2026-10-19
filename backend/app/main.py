"""FastAPI application factory."""

from __future__ import annotations

import logging
import threading
from collections.abc import AsyncIterator
from concurrent.futures import Executor
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agent.llm.anthropic_provider import AnthropicProvider
from app.api.routes import analyses, auth, conversations, datasets, health, meta
from app.auth.csrf import CSRFMiddleware
from app.auth.rate_limit import RateLimiter
from app.body_limit import BodySizeLimitMiddleware
from app.config import Settings, get_settings
from app.datasets.storage import DatasetStorage
from app.db.session import create_db_engine, create_session_factory
from app.errors import ERROR_RESPONSES, register_error_handlers
from app.logging_config import configure_logging
from app.middleware import RequestContextMiddleware
from app.services.runner import AnalysisRunner, ProviderFactory

logger = logging.getLogger(__name__)

API_PREFIX = "/api"
DOCS_URL = f"{API_PREFIX}/docs"
OPENAPI_URL = f"{API_PREFIX}/openapi.json"


def create_app(
    settings: Settings | None = None,
    *,
    provider_factory: ProviderFactory | None = None,
    run_executor: Executor | None = None,
) -> FastAPI:
    """Build the application.

    ``provider_factory`` and ``run_executor`` exist for tests and the end-to-end test server
    (a scripted LLM, synchronous execution). Production uses the configured Anthropic provider
    and a thread pool.
    """
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    # Creating the engine does not connect; connections are opened on first use.
    engine = create_db_engine(settings)
    session_factory = create_session_factory(engine)
    storage = DatasetStorage(settings.storage_dir)
    runner = AnalysisRunner(
        session_factory=session_factory,
        settings=settings,
        storage=storage,
        provider_factory=provider_factory or (lambda: AnthropicProvider.from_settings(settings)),
        executor=run_executor,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        settings.storage_dir.mkdir(parents=True, exist_ok=True)
        try:
            runner.recover_interrupted()
        except Exception:
            logger.exception("Could not check for interrupted analyses at startup")
        try:
            yield
        finally:
            runner.shutdown()
            engine.dispose()

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
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.rate_limiter = RateLimiter()
    app.state.storage = storage
    app.state.runner = runner
    app.state.provider_override = provider_factory().model_name if provider_factory else None
    app.state.ingestion_slots = threading.BoundedSemaphore(settings.max_concurrent_ingestions)
    app.dependency_overrides[get_settings] = lambda: settings

    register_error_handlers(app)

    # Middleware order: the last one added runs first (outermost).
    # RequestContext -> CORS -> CSRF -> BodySizeLimit -> routes.
    upload_path = f"{API_PREFIX}/datasets"
    upload_limit = settings.max_upload_bytes + 64 * 1024  # file + multipart overhead

    def body_limit_for(method: str, path: str) -> int:
        if method == "POST" and path == upload_path:
            return upload_limit
        return settings.max_request_body_bytes

    app.add_middleware(BodySizeLimitMiddleware, limit_for=body_limit_for)
    app.add_middleware(
        CSRFMiddleware, allowed_origins=settings.allowed_origins, path_prefix=API_PREFIX
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "X-Requested-With"],
        expose_headers=["X-Request-ID"],
        max_age=600,
    )
    # Outermost: every response, including CORS, CSRF and error responses, gets a request id
    # and security headers.
    app.add_middleware(RequestContextMiddleware, docs_paths=frozenset({DOCS_URL, OPENAPI_URL}))

    api = APIRouter(prefix=API_PREFIX, responses=ERROR_RESPONSES)
    api.include_router(health.router)
    api.include_router(auth.router)
    api.include_router(datasets.router)
    api.include_router(conversations.router)
    api.include_router(analyses.router)
    api.include_router(meta.router)
    app.include_router(api)
    return app
