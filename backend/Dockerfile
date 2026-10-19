# syntax=docker/dockerfile:1.7
# FastAPI backend: dependencies from uv.lock, non-root runtime, migrations on start.

FROM python:3.12-slim-bookworm AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12.10 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev --no-install-project
COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app

FROM python:3.12-slim-bookworm AS runtime
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app \
    && mkdir -p /data/storage \
    && chown -R app:app /data
WORKDIR /app
COPY --from=builder --chown=app:app /app /app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    STORAGE_DIR=/data/storage \
    ENVIRONMENT=production \
    FORWARDED_ALLOW_IPS=127.0.0.1
USER app
EXPOSE 8000
VOLUME ["/data/storage"]
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"]
# One worker per container by design: the rate limiter and the analysis thread pool live in the
# process, and startup marks unfinished runs as interrupted. Scale with ANALYSIS_WORKERS and
# more containers only after moving those to shared infrastructure (see KNOWN_LIMITATIONS).
# FORWARDED_ALLOW_IPS lists proxies whose X-Forwarded-For is trusted (the frontend/edge).
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.asgi:app --host 0.0.0.0 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips \"$FORWARDED_ALLOW_IPS\" --no-server-header"]
