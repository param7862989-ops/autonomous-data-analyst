"use client";

import { useEffect, useRef, useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Spinner } from "@/components/ui/spinner";
import type { ChartSpec, StoredResult } from "@/lib/analyses/api";
import { toPlotly } from "@/lib/analyses/plotly";

import { ResultTable } from "./result-table";

type PlotlyModule = typeof import("plotly.js-cartesian-dist-min");

/** Renders a chart spec with Plotly (loaded on demand) plus its source data as a table. */
export function ChartView({ spec, source }: { spec: ChartSpec; source?: StoredResult }) {
  const container = useRef<HTMLDivElement>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [showData, setShowData] = useState(false);

  useEffect(() => {
    const element = container.current;
    let plotly: PlotlyModule | null = null;
    let cancelled = false;
    import("plotly.js-cartesian-dist-min")
      .then(async (module) => {
        if (cancelled || !element) return;
        plotly = ((module as { default?: PlotlyModule }).default ?? module) as PlotlyModule;
        const figure = toPlotly(spec);
        await plotly.react(element, figure.data, figure.layout, figure.config);
        if (!cancelled) setState("ready");
      })
      .catch(() => {
        if (!cancelled) setState("error");
      });
    return () => {
      cancelled = true;
      if (plotly && element) plotly.purge(element);
    };
  }, [spec]);

  const tableId = `${spec.id}-data`;
  return (
    <figure className="rounded-(--radius-panel) border border-rule bg-surface p-4">
      <figcaption className="font-medium">{spec.title}</figcaption>
      <div className="relative mt-2">
        {state === "loading" ? (
          <p className="absolute inset-0 flex items-center justify-center gap-2 text-sm text-slate">
            <Spinner size={14} label="" /> Drawing chart…
          </p>
        ) : null}
        {state === "error" ? (
          <Alert tone="warning">The chart couldn&apos;t be drawn. Its data is in the table.</Alert>
        ) : null}
        <div
          ref={container}
          role="img"
          aria-label={`${spec.title}. ${spec.chart_type.replace("_", " ")} chart; the data is available in the table below.`}
          className="h-72 w-full"
        />
      </div>
      {spec.notes.length ? (
        <p className="mt-2 text-sm text-slate">{spec.notes.join(" ")}</p>
      ) : null}
      {source ? (
        <div className="mt-3">
          <button
            type="button"
            className="text-sm font-medium text-primary underline-offset-2 hover:underline"
            aria-expanded={showData}
            aria-controls={tableId}
            onClick={() => setShowData((open) => !open)}
          >
            {showData ? "Hide chart data" : "Show chart data"}
          </button>
          {showData ? (
            <div id={tableId} className="mt-2">
              <ResultTable result={source} compact />
            </div>
          ) : null}
        </div>
      ) : null}
    </figure>
  );
}
