# Evaluation

An analysis system can return HTTP 200 and a fluent, confident, wrong answer. The evaluation
suite measures whether answers are *correct*, separately from whether the code runs.

## What is measured

Each case (see [`backend/evals/cases.py`](../backend/evals/cases.py)) is a question about a
dataset with **planted, known facts**. Ground truth is never typed in: every expected figure and
entity is computed from the raw data with independent pandas code at evaluation time.

| Dataset | Planted facts |
|---|---|
| `sales` (the shipped sample, 7,620 orders) | Q3 2024 revenue falls about 34% versus Q2; the West region and Standing Desks drive most of the drop; ~2% of discounts and ~1% of sales channels are missing |
| `support_tickets` (synthetic, 1,500 rows) | Email is by far the slowest channel; satisfaction falls as resolution time grows; ~15% of satisfaction scores are missing |
| `employees` (synthetic, 400 rows) | Salaries differ by department; three extreme salaries; **no** attrition data |

Cases cover aggregation, ranking, trend, comparison ("why did revenue decrease in Q3?"), a
two-step follow-up chain, missing data, relationships, outliers, two unanswerable questions, an
ambiguous question ("last quarter"), a run under deliberately tight limits, and a run whose
first query is made to fail.

### Two modes

**Tool mode** (no LLM, runs in CI on every push). For each case, a reference operation (what a
careful analyst would run) goes through the real upload pipeline and the sandboxed engine, and
every ground-truth figure and entity must appear in the result. This measures the analytical
layer: if it fails, no model can answer correctly.

**Agent mode** (real LLM, costs money, run manually). The full workflow answers each question.
Per case it scores:

| Metric | Meaning |
|---|---|
| `completed` | The run finished with an answer |
| `numeric_accuracy` | Share of ground-truth figures stated in the answer (allowing written rounding and ratio-as-percent) |
| `computed_correctly` | Share of ground-truth figures present in some computed result (tool use was right even if the prose omits it) |
| `entity_accuracy` | The answer names the right region / product / month / channel |
| `tool_selection` | A sensible operation was used for the question type |
| `column_identification` | Share of required columns that the plan or tool inputs used |
| `grounded` | The grounding check passed: every figure in the answer matches a computed number, every cited id exists |
| `charts_consistent` | Every charted value is present in the result the chart cites (not scored when there is no chart) |
| `interpretation_stated` | For ambiguous questions, the plan states how it resolved the ambiguity |
| `unanswerable_handled` | For unanswerable questions, the plan declined instead of inventing an answer |
| `limits_respected` | Under tight limits, the run stayed within its tool-call and turn limits and still answered |
| `context_preserved` | For follow-ups, every figure was computed in the earlier turns' scope (period, region) and the right entity was named, though the question restates neither |
| `recovered` | With the first query failed on purpose, the agent ran another and still computed every figure |

Reports are written to `backend/evals/results/<timestamp>-<model>.json` and `.md`.

## How to run

```bash
cd backend
uv run python -m evals.run --mode tools                    # free, deterministic
GEMINI_API_KEY=... uv run python -m evals.run --mode agent      # full suite, calls the API
GEMINI_API_KEY=... uv run python -m evals.run --mode agent --case sales-q3-decline
# Claude instead: LLM_PROVIDER=anthropic ANTHROPIC_API_KEY=... uv run python -m evals.run --mode agent
```

Agent mode makes roughly 3 to 8 model calls per case (plan, tool turns, answer, possibly one
grounding retry). On a rate-limited tier, add `--pause 30` (seconds between cases) or use
`--case` to run a few at a time. The 18 cases cost a few dollars with `claude-opus-5-5`. Set
`LLM_PROVIDER` / `LLM_MODEL` to compare configurations, and pin an exact model id so reports
are reproducible.

With only Docker installed, run it in the backend image from the repository root (it reads the
key from `.env`):

```bash
docker compose run --rm --no-deps \
  -v "$PWD/backend/evals:/app/evals" -v "$PWD/data/samples:/data/samples:ro" \
  backend python -m evals.run --mode agent --pause 30
```

On a Linux host, `backend/evals/results` must be writable by uid 10001.

The harness itself is tested (`backend/tests/test_evals.py`): a correct scripted run must score
1.0 on every applicable metric, a run with invented figures must fail `numeric_accuracy` and
`grounded`, and an unanswerable question must score `unanswerable_handled` only when declined.

## Results

### Tool mode: 14 / 14 cases pass

Run on 2026-10-19 (`uv run python -m evals.run --mode tools`), and on every CI run. Every
ground-truth figure and entity was found in the reference operation's result, for example:

| Case | Ground truth (pandas) | Found in result |
|---|---|---|
| sales-q3-decline | Q2 2024 revenue 758,989; Q3 2024 497,231; change -34.49%; largest drop: West | yes |
| sales-q3-follow-up-products | largest West product drop: Standing Desk, 59,597 | yes |
| sales-revenue-outliers | 21 IQR outliers | yes |
| tickets-resolution-vs-satisfaction | Pearson correlation -0.860 | yes |
| employees-median-salary | medians 135,500 / 96,600 / 64,650 / 104,350 | yes |

### Agent mode: first live runs (one case, Gemini)

Run on 2026-11-19 against the Gemini API (free tier). Only **one case** has been run live so
far, so these are smoke-test results, not a measurement of the suite:

| Model | Case | Completed | Numeric accuracy | Entities | Grounded | Time |
|---|---|---|---|---|---|---|
| `gemini-3.5-flash-lite` | sales-q3-decline | yes | 2 / 3 | West found | yes | 42 s |
| `gemini-3.8-flash` → fallback `gemini-3.5-flash-lite` (main model overloaded) | sales-q3-decline | yes | 2 / 3 | West found | yes | 25 s |

Both runs stated Q2 2024 (758,989) and Q3 2024 (497,231) revenue correctly and named the West
region and the Standing Desk / Laptop Pro products, but did not state the -34.49% change. The
main model, `gemini-3.8-flash`, was overloaded (503/504) at the time, so no result for it exists
yet.

Found by running it live: retrying the overloaded main model three times (about two minutes per
504) used up the agent's 240-second deadline before the fallback model ran, so one run ended
with no computations. The main model is no longer retried on 429/503/504 when a fallback is
configured.

### Agent mode: full suite, 2026-11-22 (commit `185f003`)

All 18 cases completed. `gemini-3.8-flash` was requested but returned 503/504 in every case, so
**every final answer was written by `gemini-3.5-flash-lite`**. These figures describe the
fallback model. (That run's report file carries the requested model's name; reports now record
the model that answered.)

| Metric | Score | Cases |
|---|---|---|
| `completed` | 1.000 | 18 |
| `numeric_accuracy` | 0.978 | 15 |
| `computed_correctly` | 0.978 | 15 |
| `entity_accuracy` | 1.000 | 6 |
| `tool_selection` | 1.000 | 16 |
| `column_identification` | 1.000 | 14 |
| `grounded` | 0.938 | 16 |
| `charts_consistent` | 1.000 | 16, including answers with no chart |
| `interpretation_stated` | 1.000 | 2 |
| `unanswerable_handled` | 1.000 | 2 |
| `context_preserved` | 1.000 | 2 |
| `limits_respected` | 1.000 | 1 |
| `recovered` | 1.000 | 1 |

Mean 47 s per case (34 s without the two that waited on a 504), 447,721 input and 20,228 output
tokens. It is a single run on three synthetic datasets, with one or two cases behind several
metrics.

Manual review of the 18 saved summaries against the raw data:

- The figures in the summaries are correct. (Findings were not saved by that version.)
- **`sales-q3-decline` gave a wrong cause and was not penalised for it.** It called the fall a
  "sharp seasonal drop". The planted causes are West and Standing Desk, and both rose in Q3
  2023. It also never computed the -34.49% change, which did cost it a third of two metrics.
- `sales-q3-follow-up-products` failed `grounded`. The check treated the 27 in "Monitor 27in" as
  an invented figure, which is the likely cause; the flagged text was not saved, so it is not
  certain.

Changed afterwards, and **not yet re-measured against a live model**: the prompt forbids untested
causes, names containing digits are no longer read as figures, the Q3 case requires both planted
causes, and `charts_consistent` skips answers without charts. Scores from later runs are
therefore not directly comparable with this table.

## Known failure modes (expected, to watch for in agent runs)

- **Ambiguous time references**: "last quarter" could mean the latest quarter in the data
  (Q4 2024) or the calendar's last quarter relative to today. The prompt asks the model to
  state its interpretation; `interpretation_stated` checks that it does, not that it chose the
  same reading as the case.
- **Derived figures**: a model that computes a percentage in its head (instead of using the
  computed `pct_change`) produces a figure the grounding check cannot verify; it is flagged, not
  silently accepted.
- **Plausible but false causes**: no metric reads causal claims. An answer can state a cause the
  data contradicts with every figure correct, so read the "why" answers in each report.
- **Correct numbers, wrong attribution**: the grounding check confirms a figure exists in the
  results, not that it is attributed to the right entity. `entity_accuracy` and manual review
  of reports cover this partially.
- **Follow-up drift**: follow-ups see a summary of earlier turns, not their full results, so a
  follow-up must recompute what it needs; `computed_correctly` on follow-up cases measures this.
