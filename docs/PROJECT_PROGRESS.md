# Project Progress

Workflow per day: **LEARN → BUILD → TEST → UNDERSTAND → NEXT**.

Status values:

- `Not started`
- `Implemented — checkpoint pending`: code is merged and verified, but you have not yet done the
  study + understanding checkpoint. **A day is not complete until you have.**
- `Complete`: implemented, verified, and you have answered the checkpoint questions.

Learning depth scale: **Awareness** (can describe it), **Working** (can use and debug it),
**Deep** (can explain trade-offs and failure modes in an interview).

Phase order note: the master plan lists the frontend foundation before the backend. The backend
foundation is built first because the frontend's typed API client is generated from the backend's
OpenAPI schema. Authentication and the database are built before dataset upload because datasets
are private from the first line of code; retrofitting authorization later is a common source of
data-leak bugs.

---

## Day 1 — Repository foundation

- **Objective:** Create the repository, folder skeleton, ignore rules.
- **Status:** Complete (pre-existing work, commit `e2a1e0a`).

## Day 2 — Architecture and development environment (Phase 0)

- **Objective:** Fix the architecture, the safe Git workflow, and the plan.
- **Learn:**
  | Topic | Depth | Time |
  |---|---|---|
  | Why analytical queries should be isolated from application tables (blast radius, least privilege) | Deep | 45 min |
  | DuckDB: in-process OLAP, Parquet, how it differs from PostgreSQL | Working | 45 min |
  | Agent vs. workflow: what LangGraph adds over a plain loop | Awareness | 30 min |
- **Build:** `docs/ARCHITECTURE.md`, this plan, `.gitattributes`, ignore rules.
- **Acceptance:** Architecture explains every major choice and its alternative.
- **Commits:** see `git log` for `docs: define application architecture and delivery plan`.
- **Status:** Implemented — checkpoint pending.
- **Checkpoint questions:**
  1. Why is one DuckDB engine per analysis run safer than giving the LLM a read-only PostgreSQL role?
  2. What does the model control in a chart, and what can it never control?
  3. What is lost by running analyses in-process instead of in a job queue?

## Day 3 — Backend foundation (Phase 2)

- **Objective:** FastAPI app factory, typed settings, error envelope, health checks, logging, tests.
- **Learn:** FastAPI dependency injection and lifespan (Working, 1 h); pydantic-settings (Working,
  30 min); HTTP status code semantics 400/401/403/404/409/413/422/429 (Deep, 30 min).
- **Acceptance:** `pytest` passes; `/api/health` and `/api/health/ready` behave; unknown errors return a
  safe envelope without stack traces.
- **Status:** Not started.

## Day 4 — Frontend foundation (Phase 1)

- **Objective:** Next.js App Router + TypeScript + Tailwind shell, navigation, typed API client
  generated from OpenAPI, backend health indicator.
- **Learn:** App Router server vs. client components (Working, 1.5 h); TanStack Query caching,
  retries, polling (Working, 1 h); OpenAPI → TypeScript generation (Awareness, 20 min).
- **Acceptance:** `npm run build`, lint, typecheck and unit tests pass; UI shows live backend status.
- **Status:** Not started.

## Day 5 — Database and authentication (Phases 7 + 9, pulled forward)

- **Objective:** SQLAlchemy models, Alembic migrations, users/sessions, register/login/logout/me,
  CSRF protection, rate limiting, frontend auth pages.
- **Learn:** SQLAlchemy 2.0 ORM + session lifecycle (Working, 1.5 h); Alembic autogenerate vs.
  hand-written migrations (Working, 45 min); Argon2id and why not SHA-256 for passwords (Deep,
  45 min); cookie flags HttpOnly/Secure/SameSite and CSRF (Deep, 1 h).
- **Acceptance:** migrations upgrade/downgrade cleanly; auth tests cover wrong password, expired
  session, logout, CSRF header, rate limit.
- **Status:** Not started.

## Day 6 — Dataset ingestion and profiling (Phase 3)

- **Objective:** Safe CSV/XLSX ingestion, limits, normalization, Parquet storage, profiling API.
- **Learn:** Untrusted file handling — zip bombs, macro-enabled workbooks, encodings (Deep, 1 h);
  pandas dtypes and missing values (Working, 1 h); Parquet basics (Awareness, 20 min).
- **Acceptance:** tests for empty, malformed, oversized, duplicate-column, mixed-type, multi-sheet files.
- **Status:** Not started.

## Day 7 — Dataset UI (Phase 3)

- **Objective:** Upload (with sheet selection), dataset list, profile page, previews, warnings.
- **Learn:** Accessible forms and file inputs (Working, 45 min); multipart uploads (Awareness, 20 min).
- **Status:** Not started.

## Day 8 — Analytical tools and SQL safety (Phase 5)

- **Objective:** DuckDB sandbox, SQL guard, typed operations, chart-spec builder.
- **Learn:** SQL injection and why parameter binding fixes values but not identifiers (Deep, 45 min);
  ASTs and allowlists vs. blocklists (Deep, 45 min); `date_trunc`, window functions, period
  comparisons and contribution analysis (Working, 1 h).
- **Acceptance:** malicious SQL test suite rejected; operations match independent pandas computations.
- **Status:** Not started.

## Day 9 — LLM integration (Phase 4)

- **Objective:** Provider interface, Anthropic provider, structured outputs, tool calling, timeouts,
  retries, scripted test provider.
- **Learn:** Tool/function calling message flow (Deep, 1 h); structured outputs and validation
  (Working, 45 min); retryable vs. non-retryable API errors (Working, 30 min).
- **Status:** Not started.

## Day 10 — Autonomous agent (Phase 6)

- **Objective:** LangGraph workflow with explicit state, routing, bounds, cancellation, grounding.
- **Learn:** LangGraph StateGraph, reducers, conditional edges, recursion limits (Deep, 1.5 h);
  prompt injection via data values (Deep, 45 min).
- **Status:** Not started.

## Day 11 — Persistence of conversations and analyses (Phase 7)

- **Objective:** Conversations, messages, analysis runs, events; background executor; history APIs.
- **Learn:** Thread pools vs. async in FastAPI (Working, 45 min); polling vs. SSE (Awareness, 20 min).
- **Status:** Not started.

## Day 12 — Analysis workspace and charts (Phases 8 + 9)

- **Objective:** Chat workspace, activity timeline, Plotly charts, tables, follow-ups, history pages.
- **Learn:** Plotly trace types and layout (Working, 45 min); React rendering of polled state (Working, 30 min).
- **Status:** Not started.

## Day 13 — Evaluation (Phase 10)

- **Objective:** Datasets with known answers, deterministic tool evals in CI, agent evals with a
  real provider when a key is available.
- **Learn:** Evaluating LLM systems: ground truth, grading, failure taxonomies (Deep, 1 h).
- **Status:** Not started.

## Day 14 — End-to-end tests and CI (Phase 10)

- **Objective:** Playwright flow, GitHub Actions for backend, frontend, e2e, Docker build.
- **Learn:** Test pyramid; CI service containers (Working, 45 min).
- **Status:** Not started.

## Day 15 — Containers and deployment (Phase 10)

- **Objective:** Dockerfiles (non-root), Compose, deployment guide, smoke tests if access exists.
- **Learn:** Multi-stage Docker builds, health checks, volumes (Working, 1 h).
- **Status:** Not started.

## Day 16 — Security review and documentation (Phase 10)

- **Objective:** Threat model review, remaining docs, known limitations, final report.
- **Learn:** OWASP Top 10 mapping to this app (Deep, 1 h).
- **Status:** Not started.
