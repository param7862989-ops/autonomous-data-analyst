# Known limitations

What the application does not do, does imperfectly, or has not been verified to do. Each item
says why, and what would change it.

## Not verified

- **No live-model evaluation results.** The agent has been exercised end to end only with a
  scripted model, because no API key was available during development. Answer quality with a
  real model (Claude) is therefore unmeasured. The harness to measure it exists:
  `uv run python -m evals.run --mode agent` (see [EVALUATION.md](EVALUATION.md)).
- **Not deployed.** Images and Compose are built and smoke-tested in CI, but no public
  deployment exists. See [DEPLOYMENT.md](DEPLOYMENT.md).
- **Docker was not available on the development machine**; the container setup is verified only
  by the CI `docker` job.

## Architecture trade-offs

- **Single process per backend container.** Analysis runs are orchestrated in an in-process
  thread pool (each run's queries go to its own child process, see below), the rate limiter
  keeps its counters in memory, and startup marks unfinished runs as interrupted. Consequences: a restart fails in-flight analyses (users see "interrupted, ask
  again"), rate limits are per process, and running several Uvicorn workers or replicas would
  break restart recovery. Scaling out needs a shared job queue and shared rate-limit store
  (e.g. Redis), which were deliberately not added for a single-node deployment.
- **Polling, not streaming.** The UI polls a run once a second while it is active. Server-sent
  events would cut latency and requests; polling was chosen for robustness through proxies.
- **Rate limiting needs a client-IP-aware edge.** Next.js rewrites do not add
  `X-Forwarded-For`, so without the Caddy edge (production overlay) every browser appears to the
  backend as the frontend's address and per-IP limits become shared. The base Compose file
  deliberately does not trust the header, since a browser could set it. Per-account login
  limits still work.
- **Dataset size.** Uploads are capped at 25 MB, 500,000 rows, 200 columns and 10 million cells,
  and each analysis loads its dataset into an in-memory DuckDB database (512 MB limit). Larger
  data would need streaming ingestion and on-disk DuckDB databases.
- **Datasets are immutable.** There is no re-upload, append or column editing; upload a new
  version instead.

## Analysis

- **No arbitrary code execution.** The agent can only use typed operations and guarded SQL.
  Questions needing custom Python (regressions, forecasting, clustering) are answered as far as
  SQL and the operations allow, or reported as not supported. This is a deliberate security
  choice: running model-written code safely needs a separate sandbox.
- **Grounding is heuristic.** The check confirms each stated figure matches a computed number
  (allowing for rounding), not that it is attributed to the right thing; it also skips years
  and small integers. Unverified figures are flagged in the UI, not removed.
- **Type inference heuristics.** Ambiguous dates (01/02/2024) are read month-first with a
  warning; percentages are read as plain numbers (12% becomes 12); columns with more than 5%
  unparseable values stay as text. Users cannot override inferred types.
- **Follow-up context is summarised.** Follow-ups receive earlier questions, answers and result
  summaries, not full result tables, so the model recomputes what it needs.
- **Charts** support line, bar, grouped/stacked bar, histogram, scatter and heatmap with at most
  8 series (the palette size). No maps, dual axes or pie charts (deliberately).
- **Prompt injection.** Dataset values and column names reach the model as data with an explicit
  instruction to treat them as untrusted. A malicious value could still mislead the model's
  wording, but it cannot widen what the tools can access (only this user's dataset, read-only).

## Security and accounts

- **Content Security Policy allows inline scripts** (`'unsafe-inline'`), which Next.js needs
  without a nonce-based setup. The XSS defences are React escaping, no
  `dangerouslySetInnerHTML`, and entity-escaping of every data-derived chart label, legend name
  and axis title before it reaches Plotly (which would otherwise render links and markup in
  them).
- **Accounts are basic.** No email verification, password reset, multi-factor authentication,
  account deletion endpoint or admin role. Set `ALLOW_REGISTRATION=false` for private
  deployments.
- **A dev-only advisory remains** in the lint toolchain (`braces` via `eslint-config-next`; no
  patched release exists). It is not in the production image and only processes this
  repository's own glob patterns.
- **The analytics memory cap is Linux-only.** The engine's child process caps its address
  space with `RLIMIT_AS`, which Windows lacks; there, only the timeout-and-kill protection
  applies. Production images run Linux. Each analysis also pays for starting that process.
- **No audit log** of who viewed what beyond application logs.

## Product

- One dataset per conversation; no joins across datasets.
- No dark mode; light theme only.
- No export of results or charts (beyond Plotly's own image download).
