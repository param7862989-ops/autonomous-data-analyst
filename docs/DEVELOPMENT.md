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
