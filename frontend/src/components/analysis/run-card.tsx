"use client";

import { clsx } from "clsx";
import { useRef, useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { type RunDetail, isActive, useCancelRun, useRun } from "@/lib/analyses/api";
import { formatDateTime } from "@/lib/format";

import { ActivityTimeline } from "./activity-timeline";
import { AnswerView } from "./answer-view";
import { ChartView } from "./chart-view";
import { ResultTable } from "./result-table";

const STOP_NOTES: Record<string, string> = {
  iteration_limit: "The analysis reached its step limit, so the answer may be incomplete.",
  tool_limit: "The analysis reached its limit on computations, so the answer may be incomplete.",
  deadline: "The analysis reached its time limit, so the answer may be incomplete.",
  not_answerable: "This dataset doesn't contain what the question needs.",
};

function Evidence({ run, open, toggle }: { run: RunDetail; open: Set<string>; toggle: (id: string) => void }) {
  const outcome = run.outcome;
  if (!outcome?.results.length) return null;
  const cited = new Set(outcome.answer?.findings.flatMap((f) => f.evidence) ?? []);
  const ordered = [...outcome.results].sort(
    (a, b) => Number(cited.has(b.id)) - Number(cited.has(a.id)),
  );
  return (
    <section aria-label="Computed results">
      <h4 className="text-sm font-semibold">Computed results</h4>
      <ul className="mt-2 divide-y divide-rule rounded-(--radius-panel) border border-rule bg-surface">
        {ordered.map((result) => {
          const expanded = open.has(result.id);
          const panelId = `${run.id}-${result.id}`;
          return (
            <li key={result.id} id={`result-${panelId}`} className="scroll-mt-24">
              <button
                type="button"
                aria-expanded={expanded}
                aria-controls={panelId}
                onClick={() => toggle(result.id)}
                className="flex w-full items-start gap-3 px-4 py-2.5 text-left text-sm hover:bg-paper"
              >
                <span className="mt-px rounded-[3px] border border-rule-strong px-1 text-xs text-slate">
                  {result.id}
                </span>
                <span className="min-w-0 flex-1">{result.description}</span>
                <span className="shrink-0 text-slate">{expanded ? "Hide" : "Show"}</span>
              </button>
              {expanded ? (
                <div id={panelId} className="px-4 pb-4">
                  <ResultTable result={result} />
                </div>
              ) : null}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

export function RunCard({ runId, onFollowUp }: { runId: string; onFollowUp: (q: string) => void }) {
  const query = useRun(runId);
  const cancel = useCancelRun();
  const [openResults, setOpenResults] = useState<Set<string>>(new Set());
  const card = useRef<HTMLElement>(null);

  function toggle(resultId: string) {
    setOpenResults((current) => {
      const next = new Set(current);
      if (next.has(resultId)) next.delete(resultId);
      else next.add(resultId);
      return next;
    });
  }

  function cite(resultId: string) {
    setOpenResults((current) => new Set(current).add(resultId));
    requestAnimationFrame(() =>
      card.current
        ?.querySelector(`#result-${runId}-${resultId}`)
        ?.scrollIntoView({ behavior: "smooth", block: "start" }),
    );
  }

  if (query.isPending) {
    return (
      <p className="flex items-center gap-2 text-sm text-slate">
        <Spinner size={14} label="" /> Loading analysis…
      </p>
    );
  }
  if (query.isError) {
    return (
      <Alert
        tone="danger"
        title="This analysis couldn't be loaded"
        action={
          <Button variant="secondary" size="sm" onClick={() => query.refetch()}>
            Try again
          </Button>
        }
      >
        {query.error.message}
      </Alert>
    );
  }

  const run = query.data;
  const active = isActive(run.status);
  const outcome = run.outcome;
  const sources = new Map(outcome?.results.map((r) => [r.id, r]) ?? []);
  const shownCharts = outcome?.answer
    ? outcome.charts.filter((c) => outcome.answer?.chart_ids.includes(c.id))
    : (outcome?.charts ?? []);

  return (
    <article ref={card} id={`run-${run.id}`} aria-labelledby={`q-${run.id}`} className="scroll-mt-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <h3 id={`q-${run.id}`} className="max-w-[65ch] text-lg font-semibold">
          {run.question}
        </h3>
        <span className="text-sm text-slate">{formatDateTime(run.created_at)}</span>
      </header>

      <div className="mt-4 space-y-6">
        {active ? (
          <div className="rounded-(--radius-panel) border border-rule bg-surface p-4">
            <div className="mb-3 flex items-center justify-between gap-3">
              <p className="text-sm font-medium">
                {run.status === "queued" ? "Queued" : "Analysing"}
                {run.cancel_requested ? " (cancelling…)" : ""}
              </p>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => cancel.mutate(run.id)}
                disabled={run.cancel_requested}
                pending={cancel.isPending}
              >
                Cancel
              </Button>
            </div>
            <ActivityTimeline events={run.events} live />
          </div>
        ) : null}

        {run.status === "failed" ? (
          <Alert tone="danger" title="The analysis didn't finish">
            {run.error_message ?? "Something went wrong."} Ask again to retry.
          </Alert>
        ) : null}
        {run.status === "cancelled" ? <Alert tone="info">This analysis was cancelled.</Alert> : null}
        {run.status === "completed" && run.stop_reason && STOP_NOTES[run.stop_reason] ? (
          <Alert tone="info">{STOP_NOTES[run.stop_reason]}</Alert>
        ) : null}

        {outcome?.answer ? (
          <AnswerView outcome={outcome} onCite={cite} onFollowUp={onFollowUp} />
        ) : null}

        {shownCharts.length ? (
          <div className={clsx("grid gap-4", shownCharts.length > 1 && "xl:grid-cols-2")}>
            {shownCharts.map((chart) => (
              <ChartView key={chart.id} spec={chart} source={sources.get(chart.source_result_id)} />
            ))}
          </div>
        ) : null}

        {run.outcome ? <Evidence run={run} open={openResults} toggle={toggle} /> : null}

        {!active && run.events.length ? (
          <details className="text-sm">
            <summary className="cursor-pointer text-slate">
              How this was answered ({run.events.length} steps
              {run.model ? `, model ${run.model}` : ""})
            </summary>
            <div className="mt-3 space-y-3">
              {outcome?.plan?.interpretation ? (
                <p>
                  <span className="text-slate">Interpretation: </span>
                  {outcome.plan.interpretation}
                </p>
              ) : null}
              <ActivityTimeline events={run.events} live={false} />
            </div>
          </details>
        ) : null}
      </div>
    </article>
  );
}
