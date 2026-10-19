import { describe, expect, it } from "vitest";

import type { ChartSpec } from "./api";
import { DIVERGING, SERIES_COLORS, toPlotly } from "./plotly";

function spec(overrides: Partial<ChartSpec>): ChartSpec {
  return {
    id: "c1",
    chart_type: "bar",
    title: "Revenue",
    x_label: "Region",
    y_label: "Revenue",
    source_result_id: "r1",
    traces: [],
    heatmap: null,
    notes: [],
    ...overrides,
  };
}

describe("toPlotly", () => {
  it("plots exactly the spec's data, one colour per series in fixed order", () => {
    const figure = toPlotly(
      spec({
        chart_type: "line",
        traces: [
          { name: "West", x: ["2024-Q2", "2024-Q3"], y: [100, 40] },
          { name: "East", x: ["2024-Q2", "2024-Q3"], y: [90, 95.5] },
        ],
      }),
    );
    expect(figure.data).toHaveLength(2);
    expect(figure.data.map((d) => (d as { y: unknown }).y)).toEqual([
      [100, 40],
      [90, 95.5],
    ]);
    const colors = figure.data.map((d) => (d as { line: { color: string } }).line.color);
    expect(colors).toEqual([SERIES_COLORS[0], SERIES_COLORS[1]]);
    expect(figure.layout.showlegend).toBe(true);
    expect(figure.layout.hovermode).toBe("x unified");
  });

  it("omits the legend for a single series", () => {
    const figure = toPlotly(spec({ traces: [{ name: "revenue", x: ["a", "b"], y: [1, 2] }] }));
    expect(figure.layout.showlegend).toBe(false);
  });

  it("colours a single signed series by sign with the diverging poles", () => {
    const figure = toPlotly(
      spec({ traces: [{ name: "change", x: ["West", "East"], y: [-63359, 17306] }] }),
    );
    const marker = (figure.data[0] as { marker: { color: string[] } }).marker;
    expect(marker.color).toEqual([DIVERGING.negative, DIVERGING.positive]);
  });

  it("stacks stacked bars and keeps histogram bars touching", () => {
    expect(toPlotly(spec({ chart_type: "stacked_bar" })).layout.barmode).toBe("stack");
    const histogram = toPlotly(
      spec({ chart_type: "histogram", traces: [{ name: "count", x: [0, 10], y: [3, 4] }] }),
    );
    expect(histogram.layout.bargap).toBeLessThan(0.1);
  });

  it("uses a diverging scale centred on zero for correlation heatmaps", () => {
    const figure = toPlotly(
      spec({
        chart_type: "heatmap",
        heatmap: { x: ["a", "b"], y: ["a", "b"], z: [[1, -0.4], [-0.4, 1]] },
      }),
    );
    const trace = figure.data[0] as { zmid: number; zmin: number; zmax: number };
    expect([trace.zmin, trace.zmid, trace.zmax]).toEqual([-1, 0, 1]);
  });

  it("escapes text from the data so Plotly cannot render it as links or markup", () => {
    const link = '<a href="https://example.com/verify">Verify account</a>';
    const escaped = '&lt;a href="https://example.com/verify"&gt;Verify account&lt;/a&gt;';
    const bars = toPlotly(
      spec({ x_label: "<b>Region</b>", traces: [{ name: link, x: [link, "R&D", 3], y: [1, 2, 3] }] }),
    );
    const trace = bars.data[0] as { name: string; x: unknown[] };
    expect(trace.name).toBe(escaped);
    expect(trace.x).toEqual([escaped, "R&amp;D", 3]);
    expect((bars.layout.xaxis?.title as { text: string }).text).toBe("&lt;b&gt;Region&lt;/b&gt;");

    const heatmap = toPlotly(
      spec({ chart_type: "heatmap", heatmap: { x: [link, "b"], y: ["<i>a</i>", "b"], z: [[1, 0], [0, 1]] } }),
    );
    const cells = heatmap.data[0] as { x: string[]; y: string[] };
    expect(cells.x[0]).toBe(escaped);
    expect(cells.y[0]).toBe("&lt;i&gt;a&lt;/i&gt;");

    for (const figure of [bars, heatmap]) {
      expect(JSON.stringify(figure)).not.toMatch(/<(a|b|i)[ >]/);
    }
  });
});
