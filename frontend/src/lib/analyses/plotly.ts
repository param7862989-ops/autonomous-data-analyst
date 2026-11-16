import type { Config, Data, Layout } from "plotly.js";

import type { ChartSpec } from "./api";

/**
 * Categorical palette in its validated order (adjacent-pair CVD and normal-vision separation
 * checked against each mode's chart surface). Dark mode is the same eight hues re-stepped for
 * the dark surface, validated as a set - not an automatic flip. Colors are assigned to series
 * in this order and never cycled: the backend caps a chart at 8 series.
 */
export const SERIES_COLORS = [
  "#2a78d6",
  "#eb6834",
  "#1baf7a",
  "#eda100",
  "#e87ba4",
  "#008300",
  "#6250d6",
  "#e34948",
] as const;

export const SERIES_COLORS_DARK = [
  "#3987e5",
  "#d95926",
  "#199e70",
  "#c98500",
  "#d55181",
  "#008300",
  "#9085e9",
  "#e66767",
] as const;

/** Diverging poles with a neutral midpoint, for signed values and correlations. */
export const DIVERGING = { negative: "#e34948", neutral: "#f0efec", positive: "#2a78d6" } as const;
export const DIVERGING_DARK = {
  negative: "#e66767",
  neutral: "#383835",
  positive: "#3987e5",
} as const;

export type ChartTheme = "light" | "dark";

type Palette = {
  series: readonly string[];
  diverging: { negative: string; neutral: string; positive: string };
  // One hue; the end nearest zero recedes toward the surface (light on light, dark on dark).
  sequential: ReadonlyArray<readonly [number, string]>;
  ink: string;
  muted: string;
  grid: string;
  axis: string;
  surface: string;
};

const PALETTES: Record<ChartTheme, Palette> = {
  light: {
    series: SERIES_COLORS,
    diverging: DIVERGING,
    sequential: [
      [0, "#cde2fb"],
      [0.5, "#5598e7"],
      [1, "#104281"],
    ],
    ink: "#15233f",
    muted: "#5a6a80",
    grid: "#e6eaef",
    axis: "#b8c3cf",
    surface: "#ffffff",
  },
  dark: {
    series: SERIES_COLORS_DARK,
    diverging: DIVERGING_DARK,
    sequential: [
      [0, "#0d366b"],
      [0.5, "#2a78d6"],
      [1, "#b7d3f6"],
    ],
    ink: "#e7ecf3",
    muted: "#9eabbd",
    grid: "#232d3c",
    axis: "#3e4c60",
    surface: "#161e2a",
  },
};

const FONT = 'var(--font-plex-sans), "IBM Plex Sans", system-ui, sans-serif';

export type PlotlyFigure = { data: Data[]; layout: Partial<Layout>; config: Partial<Config> };

/**
 * Plotly renders a small HTML subset (links, bold, styled spans) in every text it draws: ticks,
 * legend, axis titles and hover labels. Category values and series names come from uploaded
 * data, so a cell such as `<a href="https://...">Verify</a>` would become a clickable link.
 * Escaping stops any tag from being parsed; Plotly decodes these entities for display, so "<18"
 * and "R&D" still read correctly (checked in Chromium against the bundled Plotly).
 */
export function escapePlotlyText(text: string): string {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function escapeValues<T>(values: T[]): T[] {
  return values.map((v) => (typeof v === "string" ? (escapePlotlyText(v) as T) : v));
}

function axisTitle(text: string, color: string) {
  return { text: escapePlotlyText(text), font: { size: 12, color } };
}

function isNumberList(values: unknown[]): values is number[] {
  return values.every((v) => typeof v === "number");
}

export function toPlotly(spec: ChartSpec, theme: ChartTheme = "light"): PlotlyFigure {
  const {
    series: SERIES,
    diverging: DIV,
    sequential: SEQUENTIAL,
    ink: INK,
    muted: MUTED,
    grid: GRID,
    axis: AXIS,
    surface: SURFACE,
  } = PALETTES[theme];
  const traces = (spec.traces ?? []).map((trace) => ({
    ...trace,
    name: escapePlotlyText(trace.name),
    x: escapeValues(trace.x),
  }));
  const multiSeries = traces.length > 1;
  const layout: Partial<Layout> = {
    font: { family: FONT, size: 12, color: INK },
    paper_bgcolor: SURFACE,
    plot_bgcolor: SURFACE,
    margin: { l: 64, r: 16, t: 12, b: 56 },
    showlegend: multiSeries,
    legend: { orientation: "h", x: 0, y: 1.12, font: { color: INK } },
    hoverlabel: { font: { family: FONT, color: INK }, bgcolor: SURFACE, bordercolor: AXIS },
    xaxis: {
      title: axisTitle(spec.x_label, MUTED),
      gridcolor: GRID,
      linecolor: AXIS,
      tickfont: { color: MUTED },
      zeroline: false,
      automargin: true,
    },
    yaxis: {
      title: axisTitle(spec.y_label, MUTED),
      gridcolor: GRID,
      linecolor: AXIS,
      tickfont: { color: MUTED },
      zerolinecolor: AXIS,
      tickformat: "~s",
      automargin: true,
    },
  };
  const config: Partial<Config> = {
    responsive: true,
    displaylogo: false,
    modeBarButtonsToRemove: ["lasso2d", "select2d", "autoScale2d", "toggleSpikelines"],
  };

  if (spec.chart_type === "heatmap" && spec.heatmap) {
    const values = spec.heatmap.z.flat().filter((v): v is number => typeof v === "number");
    // Values within [-1, 1] that include negatives are treated as correlations: diverging scale
    // centred on zero. Otherwise magnitude: one-hue sequential.
    const signed = values.some((v) => v < 0) && values.every((v) => Math.abs(v) <= 1);
    const data: Data[] = [
      {
        type: "heatmap",
        x: escapeValues(spec.heatmap.x),
        y: escapeValues(spec.heatmap.y),
        z: spec.heatmap.z,
        ...(signed
          ? {
              colorscale: [
                [0, DIV.negative],
                [0.5, DIV.neutral],
                [1, DIV.positive],
              ],
              zmin: -1,
              zmax: 1,
              zmid: 0,
            }
          : { colorscale: SEQUENTIAL.map(([p, c]) => [p, c]) }),
        xgap: 2,
        ygap: 2,
        hovertemplate: "%{y} / %{x}: %{z:.3~f}<extra></extra>",
        colorbar: { outlinewidth: 0, tickfont: { color: MUTED } },
      } as Data,
    ];
    return {
      data,
      layout: {
        ...layout,
        yaxis: { ...layout.yaxis, tickformat: "", autorange: "reversed" },
        xaxis: { ...layout.xaxis, tickangle: -30 },
        margin: { ...layout.margin, l: 96 },
      },
      config,
    };
  }

  if (spec.chart_type === "line") {
    return {
      data: traces.map((trace, index) => ({
        type: "scatter",
        mode: "lines+markers",
        name: trace.name,
        x: trace.x,
        y: trace.y,
        line: { width: 2, color: SERIES[index], shape: "linear" },
        marker: { size: 8, color: SERIES[index], line: { width: 2, color: SURFACE } },
        connectgaps: false,
      })) as Data[],
      layout: { ...layout, hovermode: "x unified" },
      config,
    };
  }

  if (spec.chart_type === "scatter") {
    return {
      data: traces.map((trace, index) => ({
        type: "scatter",
        mode: "markers",
        name: trace.name,
        x: trace.x,
        y: trace.y,
        marker: {
          size: 8,
          color: SERIES[index],
          opacity: 0.85,
          line: { width: 2, color: SURFACE },
        },
      })) as Data[],
      layout: { ...layout, hovermode: "closest" },
      config,
    };
  }

  // Bars: bar, grouped_bar, stacked_bar, histogram.
  const histogram = spec.chart_type === "histogram";
  const single = traces.length === 1;
  const data = traces.map((trace, index) => {
    const y = trace.y;
    // A single series with both signs (e.g. change by segment) is coloured by sign with the
    // diverging poles; direction from the baseline carries the same information.
    const signColors =
      single && !histogram && isNumberList(y.filter((v) => v !== null)) &&
      y.some((v) => (v ?? 0) < 0) && y.some((v) => (v ?? 0) > 0)
        ? y.map((v) => ((v ?? 0) < 0 ? DIV.negative : DIV.positive))
        : null;
    return {
      type: "bar",
      name: trace.name,
      x: trace.x,
      y,
      marker: { color: signColors ?? SERIES[index], line: { width: 0 } },
      hovertemplate: `${multiSeries ? "%{fullData.name}: " : ""}%{y:,.4~r}<extra>%{x}</extra>`,
    };
  }) as Data[];
  const barCount = Math.max(...traces.map((t) => t.x.length), 1) * (spec.chart_type === "grouped_bar" ? traces.length : 1);
  return {
    data,
    layout: {
      ...layout,
      barmode: spec.chart_type === "stacked_bar" ? "stack" : "group",
      // Thin bars: leave air in each band, more when there are few bars.
      bargap: histogram ? 0.04 : barCount <= 4 ? 0.6 : barCount <= 12 ? 0.4 : 0.2,
      bargroupgap: 0.1,
      barcornerradius: histogram ? 0 : 4,
      hovermode: "closest",
    } as Partial<Layout>,
    config,
  };
}
