"""Backend server for end-to-end tests: the real application with a scripted model.

Everything is real (HTTP API, PostgreSQL, uploads, DuckDB sandbox, LangGraph workflow,
persistence, background thread pool) except the language model, which is the deterministic
script in tests/scripted.py. It is never part of the production app: production always builds
the configured Anthropic provider.

Usage (environment as for the normal app, e.g. DATABASE_URL, STORAGE_DIR):
    uv run python -m tests.e2e_server --port 8000
"""

from __future__ import annotations

import argparse

import uvicorn

from app.config import Settings
from app.main import create_app
from tests.scripted import sales_provider


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    settings = Settings()
    if settings.is_production:
        raise SystemExit("Refusing to run the scripted-model test server in production.")
    app = create_app(settings, provider_factory=sales_provider)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
