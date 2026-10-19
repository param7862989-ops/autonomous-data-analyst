# Testing

Four layers, all run in CI on every push ([.github/workflows/ci.yml](../.github/workflows/ci.yml)).
None of them calls a paid API: the language model is replaced by a deterministic, scripted
provider that implements the same interface.

| Layer | Tooling | What it covers |
|---|---|---|
| Backend unit + integration | pytest, real PostgreSQL | API, auth, ingestion, profiling, analytics, SQL guard, sandbox, agent, persistence |
| Evaluation (tool mode) | `python -m evals.run --mode tools` | Analytical correctness against ground truth computed with pandas |
| Frontend unit | Vitest + Testing Library | Components, API client, polling, forms, chart translation |
| End-to-end | Playwright | The full stack in a browser, with a scripted model |
| Containers | Docker Compose in CI | Images build, stack becomes healthy, upload works through the frontend, non-root |

## Backend (`cd backend`)

```bash
export TEST_DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/ada_test
uv run pytest            # ~340 tests
uv run pytest -k sql_guard
```

Database tests migrate the test database from scratch with Alembic (never `create_all`) and
truncate every table after each test. Without `TEST_DATABASE_URL` they are skipped; CI sets
`REQUIRE_DB_TESTS=1`, which turns a skip into a failure.

| File | Focus |
|---|---|
| `test_auth.py`, `test_csrf.py`, `test_rate_limit.py` | Argon2id hashes, hashed session tokens, cookie flags, rotation, revocation, absolute and idle expiry, CSRF header/Origin/Fetch Metadata, per-IP and per-account limits |
| `test_ingest.py`, `test_inference.py`, `test_profiling.py`, `test_storage.py` | Empty, malformed, ragged, binary, oversized, multi-sheet, macro-enabled, zip-bomb and encrypted files; encodings and delimiters; type inference; profile statistics against pandas; storage keys and path traversal |
| `test_datasets_api.py` | Upload flows, sheet selection, pagination, deletion, quotas, body limits, **cross-user isolation** |
| `test_sql_guard.py`, `test_engine.py` | 74 allowed and rejected queries (DDL/DML, string amplification, CTE scope smuggling, file and network table functions, other tables, qualified names, recursive CTEs, piggybacked statements); the sandbox refusing escapes even without the guard; timeouts; row caps |
| `test_isolation.py` | The engine in its child process: same results as in-process, typed errors across the process boundary, a killed child restarts, a hung query is killed, secrets scrubbed, and (Linux only, so in CI and WSL, skipped on Windows) the memory cap stops a string-amplifying query at the production default |
| `test_operations.py`, `test_charts.py` | Every analytical operation compared with an independent pandas computation; values are bound, not interpolated; chart data equals result data |
| `test_anthropic_provider.py` | The real Anthropic SDK through a mock HTTP transport: request shape, tool-call parsing, replay, structured output, refusal, truncation, 400/401/429/5xx, timeouts |
| `test_agent.py`, `test_grounding.py` | Workflow routing, unanswerable questions, invalid tool input, rejected SQL, iteration/tool/deadline limits, cancellation, model failures, structured-output retry, grounding retry and persistent-failure reporting |
| `test_analyses_api.py` | Full flow through the API, follow-ups use only the same conversation, **cross-user isolation on every route**, model not configured, one active run per conversation (including two simultaneous starts), cancellation, restart recovery |
| `test_migrations.py` | Upgrade/downgrade round trip; models match migrations; migration 0004 resolves pre-existing duplicate active runs |
| `test_evals.py` | Tool-mode evals pass; the scorer rewards a correct run and catches invented figures |

## Frontend (`cd frontend`)

```bash
npm test                 # Vitest, ~65 tests
npm run lint && npm run typecheck
```

Components are tested with mocked `fetch` (and a mocked Plotly module, since jsdom cannot render
charts): auth forms and safe redirects, the session guard, upload validation and the sheet
selection round trip, dataset list states, row pagination, the run card's polling from running
to completed, failure and cancel states, answer highlighting of verified and unverified
figures, the question composer, and the Plotly translation (palette order, legends, diverging
colours, heatmaps).

## End-to-end (`cd frontend`)

```bash
npm run build
E2E_DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/ada_e2e npx playwright test
```

Playwright starts `backend/tests/e2e_server.py` (the real application with a scripted model) and
the production frontend build. The main test registers, uploads the sample, checks the profile
and rows, asks "Why did revenue decrease in Q3?", checks the grounded answer, highlighted
figures, the rendered chart, the cited result table and the activity trail, asks a follow-up,
reloads and finds both in History, signs out, and confirms a second user sees nothing and gets
"not found" for the first user's dataset and conversation URLs.

## Tests that need a real model

Agent-mode evaluation (`python -m evals.run --mode agent`) calls the configured provider and
costs money, so it is never part of CI. See [EVALUATION.md](EVALUATION.md).

## Rules followed

- Failing tests are fixed at the cause or, when the test's assumption was wrong, the test is
  corrected with the reason recorded; assertions are never loosened to pass.
- Numbers are checked against independent computations, not against the code under test.
