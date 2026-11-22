# Known limitations

What the application does not do, does imperfectly, or has not been verified to do. Each item
says why, and what would change it.

## Not verified

- **Live-model evaluation is one run of 18 synthetic cases.** It measured the fallback model
  (`gemini-3.5-flash-lite`), because `gemini-3.8-flash` was unavailable in every case; the main
  model is unmeasured. The prompt changes made after that run were re-run on three cases only. See
  [EVALUATION.md](EVALUATION.md).
- **Gemini model availability varies.** On the free tier the newest Flash models are sometimes
  overloaded; the provider then falls back to `GEMINI_FALLBACK_MODEL` for the rest of the run,
  which answers faster but less thoroughly. If `LLM_MODEL` is the fallback model there is no
  fallback: an overload that outlasts the retries fails the question (1 of 9 in the last check).
- **Not deployed.** Images and Compose are built and smoke-tested in CI, but no public
  deployment exists. See [DEPLOYMENT.md](DEPLOYMENT.md).
- **Containers are tested on one machine at a time.** CI builds and smoke-tests the stack on
  x86-64 Linux; it has also been run on Apple Silicon with Docker Desktop. The production
  overlay has never faced the internet or a publicly trusted certificate.

## Architecture trade-offs

- **Single process per backend container.** Analysis runs are orchestrated in an in-process
  thread pool (each run's queries go to its own child process, see below), the rate limiter
  keeps its counters in memory, and startup marks unfinished runs as interrupted. Consequences: a restart fails in-flight analyses (users see "interrupted, ask
  again"), rate limits are per process, and running several Uvicorn workers or replicas would
  break restart recovery. Scaling out needs a shared job queue and shared rate-limit store
  (e.g. Redis), which were deliberately not added for a single-node deployment.
- **Live updates are per process.** The UI follows a run over Server-Sent Events and polls once
  a second if the stream fails. Wake-ups and the per-user stream limit live in memory; a stream
  also re-reads the run every 2 seconds.
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
- **Causes are not checked.** Grounding verifies figures, not explanations. In the live run an
  answer called a planted drop "seasonal", which the data contradicts, and passed. The prompt now
  forbids untested causes, but nothing enforces it: in a later check two of three hypotheses,
  though labelled as such, were still worded as certainties ("was driven by").
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
- **The local stack is local.** Compose publishes the app on 127.0.0.1 only. `FRONTEND_BIND`
  can change that, but there is no TLS without the production overlay.
- **A dev-only advisory remains** in the lint toolchain (`braces` via `eslint-config-next`; no
  patched release exists). It is not in the production image and only processes this
  repository's own glob patterns.
- **The analytics memory cap is Linux-only.** The engine's child process caps its address
  space with `RLIMIT_AS`, which Windows lacks and macOS rejects; there, only the
  timeout-and-kill protection applies. Production images run Linux. Each analysis also pays for starting that process.
- **No audit log** of who viewed what beyond application logs.

## Product

- One dataset per conversation; no joins across datasets.
- Exports are per analysis: each computed result as CSV (up to the engine's row cap of
  `MAX_RESULT_ROWS`, default 1,000) and the analysis as a Markdown report (tables in the report
  show the first 50 rows). Charts download as PNG through Plotly's toolbar. There is no PDF
  export and no export of a whole conversation in one file.
