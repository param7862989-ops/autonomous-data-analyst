# Development

## Prerequisites

| Tool | Version | Used for |
|---|---|---|
| Python | 3.12 | backend (uv installs it if missing) |
| [uv](https://docs.astral.sh/uv/) | ≥ 0.5 | Python dependencies and virtual environment (`backend/.venv`) |
| Node.js | ≥ 22.12 (developed on 24) | frontend |
| PostgreSQL | 16 | application database (or use Docker Compose) |
| Docker + Compose | Compose ≥ 2.24 | optional: the whole stack in containers |

## Quick start with Docker

```bash
cp .env.example .env          # set POSTGRES_PASSWORD; ANTHROPIC_API_KEY enables analysis
docker compose up --build -d
open http://localhost:3000    # register, upload data/samples/sales.csv, ask a question
docker compose down           # stop (add -v to delete the database and uploaded data)
```

## Running the parts locally

### Database

Create a database for development and one for tests, then point the backend at them:

```bash
createdb ada_dev && createdb ada_test
# in .env (repository root):
DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/ada_dev
```

### Backend

```bash
cd backend
uv sync                                    # creates backend/.venv from uv.lock
uv run alembic upgrade head                # create/upgrade the schema
uv run uvicorn app.asgi:app --reload --port 8000
```

- API docs: <http://localhost:8000/api/docs>
- Without `ANTHROPIC_API_KEY`, everything works except asking questions.
- To try the whole flow without a key, run the test server with the scripted model instead:
  `uv run python -m tests.e2e_server --port 8000` (it answers the sample "Why did revenue
  decrease in Q3?" analysis with real computations and a scripted narrative).

Migrations: never change the schema by hand.

```bash
uv run alembic revision --autogenerate --rev-id 0005 -m "describe change"   # then review it
uv run alembic downgrade -1
```

### Frontend

```bash
cd frontend
npm ci
npm run dev                  # http://localhost:3000, proxies /api to localhost:8000
```

The browser only talks to the Next.js origin; Next.js rewrites `/api/*` to
`BACKEND_INTERNAL_URL` (default `http://localhost:8000`, fixed at build time). For a
production-like run: `npm run build && npm start` (the standalone server).

## Checks

Run everything CI runs, except the Docker job, with one command from the repository root:

```bash
export TEST_DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/ada_test
./scripts/check.sh           # add --e2e to also run Playwright (needs E2E_DATABASE_URL)
```

It runs ruff, mypy, pytest, the tool-mode evaluation, regenerates the OpenAPI schema and
TypeScript types (and fails if they changed), ESLint, tsc, Vitest and the production build.

### The API contract

The frontend's types come from the backend's OpenAPI schema. After changing any route or
response model, regenerate and commit both files:

```bash
cd backend && uv run python -m app.openapi_export ../frontend/src/lib/api/openapi.json
cd ../frontend && npm run gen:api
```

## Project layout

```
backend/
  app/            FastAPI application (see docs/ARCHITECTURE.md for modules)
  migrations/     Alembic migrations
  evals/          Evaluation datasets, cases, scoring and runner
  tests/          pytest suite, scripted model, E2E server
frontend/
  src/app/        Next.js routes: (auth) sign-in pages, (app) the signed-in application
  src/components/ UI, datasets, analysis workspace
  src/lib/        API client (generated types), data hooks, formatting, chart translation
  e2e/            Playwright tests
data/samples/     Synthetic sample dataset and its generator
deploy/           Production Compose overlay and Caddy configuration
docs/             Architecture, API, security, data model, testing, evaluation, deployment
scripts/          check.sh, smoke_test.sh
```
