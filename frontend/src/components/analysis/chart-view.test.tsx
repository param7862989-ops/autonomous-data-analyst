import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ChartSpec, StoredResult } from "@/lib/analyses/api";
import { renderWithQuery } from "@/test/utils";

import { ChartView } from "./chart-view";

const plotly = vi.hoisted(() => ({ react: vi.fn(), purge: vi.fn() }));
vi.mock("plotly.js-cartesian-dist-min", () => ({ default: plotly }));

beforeEach(() => {
  plotly.react.mockReset().mockResolvedValue(undefined);
  plotly.purge.mockReset();
});

const SPEC = {
  id: "c1",
  chart_type: "bar",
  title: "Change by region",
  x_label: "Region",
  y_label: "Change",
  source_result_id: "r1",
  traces: [{ name: "change", x: ["West", "East"], y: [-157871.28, 17306.03] }],
  heatmap: null,
  notes: [],
} as ChartSpec;
const SOURCE = {
  id: "r1",
  tool: "execute_analysis",
  operation: "aggregate",
  description: "Change by region",
  table: {
    columns: [
      { name: "segment", type: "VARCHAR" },
      { name: "change", type: "DOUBLE" },
    ],
    rows: [["West", -157871.28]],
    row_count: 1,
    truncated: false,
  },
  summary: {},
  notes: [],
  sql: null,
  arguments: null,
} as StoredResult;

describe("ChartView", () => {
  it("draws exactly the data in the spec", async () => {
    const { unmount } = renderWithQuery(<ChartView spec={SPEC} />);
    await waitFor(() => expect(screen.queryByText("Drawing chart…")).toBeNull());
    const [element, data] = plotly.react.mock.calls[0];
    expect(data[0].y).toEqual([-157871.28, 17306.03]);
    unmount();
    expect(plotly.purge).toHaveBeenCalledWith(element);
  });

  it("falls back to the data table when drawing fails", async () => {
    plotly.react.mockRejectedValue(new Error("cannot draw"));
    renderWithQuery(<ChartView spec={SPEC} source={SOURCE} />);
    expect(await screen.findByText(/chart couldn't be drawn/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Show chart data" }));
    expect(screen.getByRole("cell", { name: "West" })).toBeInTheDocument();
  });
});
