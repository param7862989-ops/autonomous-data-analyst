# Autonomous Data Analyst

Upload a CSV or Excel file, review an automatic profile of it, and ask questions in plain
language, such as *"Why did revenue decrease in Q3?"*. A bounded agent plans the analysis, runs
real computations on your data with validated tools, draws charts from the computed results,
and answers with evidence. Every figure in the answer is checked against the numbers it
computed.

![An answer with highlighted, verified figures](docs/images/analysis-answer.png)

## What it does

- **Safe ingestion** of CSV and XLSX: size, row, column and cell limits; macro-enabled,
  encrypted and legacy workbooks rejected; zip bombs caught before parsing; formulas never
  evaluated; encodings, delimiters, duplicate and empty headers handled; sheet selection for
  multi-sheet workbooks.
- **Automatic profiling**: inferred types (numbers with currency/thousands formats, dates with
  ambiguity warnings, booleans, codes with leading zeros, categories, free text), missing
  values, duplicates, statistics, histograms, top values and data-quality warnings.
- **An analysis agent** (LangGraph) that plans, chooses tools, runs them, inspects the results,
  does more analysis when justified, and stops within explicit limits on turns, tool calls and
  time. It shows high-level activity derived from the operations that actually ran, never its
  reasoning.
- **Validated analytical tools**: typed operations (aggregate, time series, period comparison
  with contribution analysis, distribution, correlation, outliers, missing values, row lookup)
  and guarded read-only SQL, all executed in a per-analysis DuckDB sandbox that can only see
  the one dataset, inside a separate, memory-capped process.
- **Grounded answers**: facts cite the results they come from; possible explanations are
  labelled as hypotheses; figures that match computed numbers are highlighted, and any that
  don't are flagged.
- **Charts from results only**: the model chooses the chart's shape, while the data points are
  copied from a computed result (Plotly, with a colour-blind-checked palette and a table view).
- **Conversations** with follow-up questions, history, cancellation, and persistence.
- **Accounts** with Argon2id passwords, server-side sessions in HttpOnly cookies, CSRF
  protection, rate limits, and strict per-user isolation.

![Computed evidence behind the answer](docs/images/analysis-evidence.png)

> The screenshots show the app running locally. The numbers are real computations on the
> sample dataset; the answer's wording comes from the deterministic test model used in
> development and CI (see [Status](#status)).

## Architecture

```mermaid
flowchart LR
    B[Browser] --> N[Next.js<br/>App Router, Tailwind, Plotly]
    N -- "/api/* (same origin, HttpOnly cookie)" --> F[FastAPI]
    F --> P[(PostgreSQL<br/>users, sessions, datasets,<br/>conversations, runs, events)]
    F --> S[(Private storage<br/>one Parquet file per dataset)]
    F --> W[Background runner<br/>bounded thread pool]
    W --> G[LangGraph agent<br/>plan, act, tools, answer, validate]
    G --> T[Validated tools]
    T --> D[DuckDB sandbox<br/>one dataset, no file/network access]
    G --> L[LLM provider interface<br/>Anthropic Claude]
```

Key decisions (details in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)):

| Decision | Why |
|---|---|
| One in-memory DuckDB per analysis, holding only that dataset, external access disabled and config locked | Model-written SQL physically cannot reach application tables, other users' data, files or the network |
| SQL checked as an allowlist over the parsed syntax tree, and the re-generated SQL is what runs | A "starts with SELECT" check is trivially bypassed; executing the validated tree avoids parser differentials |
| Typed operations preferred over SQL | Deterministic, testable without an LLM, identifiers schema-checked and values bound |
| Charts copy data from results | The model can't plot numbers it didn't compute |
| Deterministic grounding check with one corrective retry | Invented or miscalculated figures are caught and flagged, not trusted |
| No arbitrary Python execution | Not needed for the features; avoids a code sandbox |
| Polling and an in-process worker pool | Simple and robust on one node; the trade-offs are documented |

## Tech stack

| Area | Technology |
|---|---|
| Frontend | Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS 4, TanStack Query, Plotly.js, typed client generated from OpenAPI |
| Backend | Python 3.12, FastAPI, Pydantic 2, SQLAlchemy 2, Alembic, PostgreSQL 16, pandas, PyArrow, DuckDB, sqlglot |
| AI | LangGraph, Anthropic SDK (Claude, `claude-opus-5-5` by default) behind a provider interface, structured outputs, tool use |
| Quality | pytest, Vitest, Testing Library, Playwright, ruff, mypy, ESLint, GitHub Actions |
| Infrastructure | Docker, Docker Compose, Caddy (TLS edge), uv, npm |

## Quick start

With Docker:

```bash
git clone https://github.com/param7862989-ops/autonomous-data-analyst.git
cd autonomous-data-analyst
cp .env.example .env     # set POSTGRES_PASSWORD; set ANTHROPIC_API_KEY to enable questions
docker compose up --build -d
```

Open <http://localhost:3000>, create an account, upload
[`data/samples/sales.csv`](data/samples/sales.csv) (a synthetic dataset with a planted Q3 2024
revenue drop), and ask *"Why did revenue decrease in Q3?"*.

Without Docker, see [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md): run PostgreSQL, then
`uv sync && uv run alembic upgrade head && uv run uvicorn app.asgi:app` in `backend/` and
`npm ci && npm run dev` in `frontend/`.

### Configuration

All settings are environment variables, documented in [`.env.example`](.env.example). The ones
that matter most:

| Variable | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Enables analysis. Without it, upload and profiling work and the UI says analysis is unavailable |
| `LLM_MODEL`, `LLM_EFFORT` | Model and effort (default `claude-opus-5-5`, `medium`) |
| `POSTGRES_PASSWORD` / `DATABASE_URL` | Database (Compose builds the URL itself) |
| `ALLOWED_ORIGINS` / `PUBLIC_ORIGIN` | The browser origin, used for CORS and CSRF checks |
| `ALLOW_REGISTRATION` | Turn off open sign-up for private deployments |
| `AGENT_MAX_ITERATIONS`, `AGENT_MAX_TOOL_CALLS`, `AGENT_DEADLINE_SECONDS` | Agent bounds |
| `MAX_UPLOAD_BYTES`, `MAX_DATASET_ROWS`, ... | Upload limits |

### Database

The schema is managed only by Alembic migrations; the backend container applies them on start.
Locally: `cd backend && uv run alembic upgrade head`. See [docs/DATA_MODEL.md](docs/DATA_MODEL.md).

## Testing

```bash
export TEST_DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/ada_test
./scripts/check.sh       # backend lint/types/tests, tool-mode evals, API contract, frontend lint/types/tests/build
```

About 340 backend tests (against real PostgreSQL), 66 frontend tests, a Playwright
end-to-end suite, the evaluation suite and a Docker smoke test all run in CI on every push, with
no paid API calls. Highlights: 74 SQL-injection and sandbox-escape cases; every analytical
operation checked against independent pandas computations; cross-user isolation on every
route, in the API and in the browser. See [docs/TESTING.md](docs/TESTING.md).

## Evaluation

The evaluation suite asks 17 questions about three datasets with planted facts, with ground
truth computed independently from the raw data. **Tool mode passes 14/14 cases** in CI: the
analytical layer computes every ground-truth figure correctly. **Agent mode** (the full workflow
with a real model, scoring numeric accuracy, tool choice, columns, grounding, chart/data
consistency, ambiguity and unanswerable handling) is implemented and tested with a scripted
model, but **has not been run against a live model yet**, so no answer-quality numbers are
claimed. See [docs/EVALUATION.md](docs/EVALUATION.md).

## Deployment

A production Compose overlay adds Caddy for automatic TLS; the recommended target is one small
VM. Images build and the stack is smoke-tested in CI, but **no public deployment exists yet**.
See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md), including which services cost money.

## Security

Threat model, controls and their tests: [docs/SECURITY.md](docs/SECURITY.md). In short:
private-by-default data with owner checks on every query (others get `404`), sandboxed and
allowlisted analytics, hardened uploads, Argon2id and hashed session tokens in HttpOnly
cookies, CSRF checks, rate limits, request-size limits, safe errors, non-root containers, pinned
CI actions and a runtime dependency audit.

## Status

| Area | State |
|---|---|
| Upload, profiling, auth, conversations, history | Working and tested (unit, integration, E2E) |
| Agent workflow, tools, sandbox, charts, grounding | Working and tested with a scripted model |
| Answer quality with a real model | **Not yet measured**: needs an API key (`evals.run --mode agent`) |
| Containers | Built and smoke-tested in CI |
| Public deployment | **Not done**: needs a server and domain |

Known limitations are listed honestly in
[docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md). Build history and learning checkpoints:
[docs/PROJECT_PROGRESS.md](docs/PROJECT_PROGRESS.md).

## Documentation

[Architecture](docs/ARCHITECTURE.md) · [API](docs/API.md) · [Data model](docs/DATA_MODEL.md) ·
[Security](docs/SECURITY.md) · [Testing](docs/TESTING.md) · [Evaluation](docs/EVALUATION.md) ·
[Deployment](docs/DEPLOYMENT.md) · [Development](docs/DEVELOPMENT.md) ·
[Known limitations](docs/KNOWN_LIMITATIONS.md) · [Progress](docs/PROJECT_PROGRESS.md)
