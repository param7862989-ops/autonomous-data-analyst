# API

The interactive OpenAPI documentation is served at **`/api/docs`** (disabled in the production
overlay) and the schema at `/api/openapi.json`. The committed copy,
[`frontend/src/lib/api/openapi.json`](../frontend/src/lib/api/openapi.json), is what the frontend's
TypeScript client is generated from; CI fails if it is stale.

## Conventions

- **Base path** `/api`. Browsers call it on the frontend's origin; Next.js forwards it to the
  backend.
- **Authentication**: an `ada_session` cookie (HttpOnly, SameSite=Lax, Secure in production)
  set by `register` and `login`. Every route except health, register and login requires it and
  returns `401` without a valid session.
- **CSRF**: every `POST`/`PATCH`/`DELETE` must send `X-Requested-With: fetch`; requests with a
  foreign `Origin` or `Sec-Fetch-Site: cross-site` get `403 csrf_failed`.
- **Ownership**: a dataset, conversation or analysis that belongs to another user is reported
  as `404`, exactly like one that does not exist.
- **Pagination**: list endpoints take `limit` (max 100) and `offset` and return
  `{items, total, limit, offset}`.
- **Errors** always use one envelope, never stack traces, file paths or submitted values:

  ```json
  {"error": {"code": "not_found", "message": "Dataset not found.", "details": null,
             "request_id": "7d8444c705c64691aa16162e0d12b82b"}}
  ```

  Every response also carries `X-Request-ID`, which appears in server logs.

## Endpoints

| Method | Path | Purpose | Success |
|---|---|---|---|
| `GET` | `/api/health` | Liveness probe | 200 |
| `GET` | `/api/health/ready` | Readiness: database and storage (503 when not ready) | 200 |
| `POST` | `/api/auth/register` | Create an account and sign in | 201 |
| `POST` | `/api/auth/login` | Sign in | 200 |
| `POST` | `/api/auth/logout` | Sign out (revokes the session server-side) | 204 |
| `GET` | `/api/auth/me` | The signed-in user | 200 |
| `GET` | `/api/config` | Whether analysis is enabled, and the model | 200 |
| `POST` | `/api/datasets` | Upload a CSV or XLSX file (multipart: `file`, optional `sheet_name`, `name`) | 201 |
| `GET` | `/api/datasets` | List your datasets | 200 |
| `GET` | `/api/datasets/limits` | Upload limits for this server | 200 |
| `GET` | `/api/datasets/{dataset_id}` | Dataset details and profile | 200 |
| `GET` | `/api/datasets/{dataset_id}/preview` | A page of rows (`offset`, `limit` ≤ 200) | 200 |
| `DELETE` | `/api/datasets/{dataset_id}` | Delete a dataset, its file and its conversations | 204 |
| `POST` | `/api/conversations` | Start a conversation about a dataset (`{dataset_id, title?}`) | 201 |
| `GET` | `/api/conversations` | List your conversations (optional `dataset_id`) | 200 |
| `GET` | `/api/conversations/{conversation_id}` | A conversation and its questions | 200 |
| `PATCH` | `/api/conversations/{conversation_id}` | Rename (`{title}`) | 200 |
| `DELETE` | `/api/conversations/{conversation_id}` | Delete a conversation and its analyses | 204 |
| `POST` | `/api/conversations/{conversation_id}/analyses` | Ask a question (`{question}`, ≤ 2,000 chars) | 202 |
| `GET` | `/api/analyses` | Analysis history (optional `dataset_id`, `conversation_id`) | 200 |
| `GET` | `/api/analyses/{run_id}` | An analysis: status, activity events and outcome | 200 |
| `POST` | `/api/analyses/{run_id}/cancel` | Cancel a queued or running analysis | 202 |

## Asking a question

```text
POST /api/conversations/{id}/analyses   {"question": "Why did revenue decrease in Q3?"}
  -> 202 {"id": "...", "status": "queued", ...}

GET /api/analyses/{id}                   (poll about once a second)
  -> {"status": "running", "events": [{"key": "plan", "label": "Planning analysis",
                                       "status": "running", ...}, ...]}
  -> {"status": "completed", "events": [...], "outcome": {
        "plan":    {...},
        "answer":  {"summary": "...", "findings": [{"statement": "...", "kind": "fact",
                    "evidence": ["r1"]}], "caveats": [...], "chart_ids": ["c1"], ...},
        "results": [{"id": "r1", "operation": "period_comparison", "description": "...",
                     "table": {"columns": [...], "rows": [...], "row_count": 4,
                               "truncated": false},
                     "summary": {...}, "arguments": {...}}],
        "charts":  [{"id": "c1", "chart_type": "bar", "source_result_id": "r1",
                     "traces": [{"name": "change", "x": [...], "y": [...]}], ...}],
        "grounding": {"checked_numbers": 5, "unverified_numbers": [], ...},
        "usage":   {"input_tokens": ..., "output_tokens": ..., "model": "..."}}}
```

`status` ends as `completed`, `failed` (with a safe `error_code` / `error_message`) or
`cancelled`. `stop_reason` says why a completed run stopped (`completed`, `not_answerable`,
`iteration_limit`, `tool_limit`, `deadline`).

## Error codes

| Status | Codes |
|---|---|
| 400 | `bad_request` |
| 401 | `not_authenticated`, `session_expired`, `invalid_credentials` |
| 403 | `csrf_failed`, `registration_disabled` |
| 404 | `not_found` |
| 409 | `email_taken`, `dataset_quota_exceeded`, `analysis_in_progress` |
| 413 | `payload_too_large`, `file_too_large`, `workbook_too_large` |
| 422 | `validation_error`, `invalid_file`, `unsupported_file_type`, `file_type_mismatch`, `empty_file`, `no_data_rows`, `malformed_file`, `too_many_rows`, `too_many_columns`, `too_many_cells`, `sheet_required` (with `details.sheets`), `sheet_not_found` |
| 429 | `rate_limited` (with `Retry-After`) |
| 503 | `service_unavailable`, `llm_not_configured`, `ingestion_busy` |

Analysis-level failures are not HTTP errors: they are stored on the run (`error_code` such as
`llm_timeout`, `llm_rate_limited`, `llm_unavailable`, `llm_refused`, `llm_bad_response`,
`interrupted`, `internal_error`).
