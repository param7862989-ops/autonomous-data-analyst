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
ambiguous question ("last quarter"), and a run under deliberately tight limits.

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
| `charts_consistent` | Every charted value is present in the result the chart cites |
| `interpretation_stated` | For ambiguous questions, the plan states how it resolved the ambiguity |
| `unanswerable_handled` | For unanswerable questions, the plan declined instead of inventing an answer |
| `limits_respected` | Under tight limits, the run stayed within them and still answered |

Reports are written to `backend/evals/results/<timestamp>-<model>.json` and `.md`.

## How to run

```bash
cd backend
uv run python -m evals.run --mode tools                    # free, deterministic
ANTHROPIC_API_KEY=... uv run python -m evals.run --mode agent    # full suite, calls the API
ANTHROPIC_API_KEY=... uv run python -m evals.run --mode agent --case sales-q3-decline
```

Agent mode makes roughly 3 to 8 model calls per case (plan, tool turns, answer, possibly one
grounding retry); 17 cases cost on the order of a few dollars with `claude-opus-5-5` at medium
effort. Set `LLM_MODEL` / `LLM_EFFORT` to compare configurations.

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

### Agent mode: not yet run against a live model

No language-model API key was available while this was built, so **no agent-mode results exist
yet** and none are claimed. The harness, scoring and report format are implemented and tested
with a scripted model. To produce real numbers, run the agent-mode command above with a key and
record the report here.

## Known failure modes (expected, to watch for in agent runs)

- **Ambiguous time references**: "last quarter" could mean the latest quarter in the data
  (Q4 2024) or the calendar's last quarter relative to today. The prompt asks the model to
  state its interpretation; `interpretation_stated` checks that it does, not that it chose the
  same reading as the case.
- **Derived figures**: a model that computes a percentage in its head (instead of using the
  computed `pct_change`) produces a figure the grounding check cannot verify; it is flagged, not
  silently accepted.
- **Correct numbers, wrong attribution**: the grounding check confirms a figure exists in the
  results, not that it is attributed to the right entity. `entity_accuracy` and manual review
  of reports cover this partially.
- **Follow-up drift**: follow-ups see a summary of earlier turns, not their full results, so a
  follow-up must recompute what it needs; `computed_correctly` on follow-up cases measures this.
