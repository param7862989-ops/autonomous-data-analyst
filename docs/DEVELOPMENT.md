# Development

## Prerequisites

| Tool | Version | Used for |
|---|---|---|
| Python | 3.12 | backend |
| [uv](https://docs.astral.sh/uv/) | ≥ 0.5 | Python dependency management and virtual environment |
| Node.js | ≥ 20 (developed on 24) | frontend |
| PostgreSQL | 16 | application database (or use Docker Compose) |
| Docker + Compose | recent | optional: full stack in containers |

## Backend

```bash
cd backend
uv sync                     # creates backend/.venv from uv.lock
cp ../.env.example ../.env  # then edit values
uv run uvicorn app.asgi:app --reload --port 8000
```

- API docs: <http://localhost:8000/api/docs>
- Liveness: `GET /api/health`; readiness: `GET /api/health/ready`

### Quality checks

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
```

## Frontend

```bash
cd frontend
npm ci
npm run dev                 # http://localhost:3000
```

The browser only talks to the Next.js origin. Next.js rewrites `/api/*` to the backend at
`BACKEND_INTERNAL_URL` (default `http://localhost:8000`), so the session cookie is first-party.
With `output: "standalone"` the rewrite target is fixed at **build** time.

### Quality checks

```bash
npm run lint
npm run typecheck
npm test
npm run build
```

## API contract

The frontend's types are generated from the backend's OpenAPI schema. After changing any backend
route or schema:

```bash
cd backend && uv run python -m app.openapi_export ../frontend/src/lib/api/openapi.json
cd ../frontend && npm run gen:api
```

Commit both generated files. CI fails if they are stale.
