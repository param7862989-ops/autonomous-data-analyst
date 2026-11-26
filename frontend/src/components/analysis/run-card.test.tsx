import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { stubBlobUrls } from "@/test/blob-urls";
import { jsonResponse, mockFetch, renderWithQuery } from "@/test/utils";

import { RunCard } from "./run-card";

vi.mock("plotly.js-cartesian-dist-min", () => ({
  default: { react: vi.fn(async () => undefined), purge: vi.fn() },
}));

afterEach(() => vi.unstubAllGlobals());

const BASE = {
  id: "run-1",
  conversation_id: "conv-1",
  dataset_id: "ds-1",
  question: "Why did revenue decrease in Q3?",
  stop_reason: null,
  answer_summary: null,
  created_at: "2026-10-19T10:00:00Z",
  finished_at: null,
  error_code: null,
  error_message: null,
  model: "claude-opus-5-5",
  cancel_requested: false,
  started_at: "2026-10-19T10:00:01Z",
  outcome: null,
};

const event = (key: string, seq: number, label: string, status: string) => ({
  key,
  seq,
  kind: "step",
  label,
  status,
  detail: null,
  result_id: null,
  updated_at: "2026-10-19T10:00:02Z",
});

const RESULT = {
  id: "r1",
  tool: "execute_analysis",
  operation: "period_comparison",
  description: "Sum of Revenue by Region",
  table: {
    columns: [
      { name: "segment", type: "VARCHAR" },
      { name: "change", type: "DOUBLE" },
    ],
    rows: [
      ["West", -157871.28],
      ["East", 17306.03],
    ],
    row_count: 2,
    truncated: false,
  },
  summary: { change: -261758.27 },
  notes: [],
  sql: null,
};

const COMPLETED = {
  ...BASE,
  status: "completed",
  stop_reason: "completed",
  answer_summary: "Revenue fell.",
  events: [event("inspect", 1, "Inspecting dataset", "completed")],
  outcome: {
    status: "completed",
    stop_reason: "completed",
    plan: null,
    answer: {
      summary: "Revenue fell by $261,758.",
      findings: [{ statement: "West fell by $157,871.", kind: "fact", evidence: ["r1"] }],
      caveats: [],
      chart_ids: ["c1"],
      follow_up_questions: [],
    },
    results: [RESULT],
    charts: [
      {
        id: "c1",
        chart_type: "bar",
        title: "Change by region",
        x_label: "Region",
        y_label: "Change",
        source_result_id: "r1",
        traces: [{ name: "change", x: ["West", "East"], y: [-157871.28, 17306.03] }],
        heatmap: null,
        notes: [],
      },
    ],
    grounding: { checked_numbers: 2, unverified_numbers: [], invalid_references: [], unsupported_facts: [] },
    error_code: null,
    error_message: null,
    iterations: 2,
    tool_calls: 2,
    usage: {},
  },
};

describe("RunCard", () => {
  it("shows live activity while running, then the answer, chart and evidence", async () => {
    let polls = 0;
    mockFetch(() => {
      polls += 1;
      if (polls === 1) {
        return jsonResponse({
          ...BASE,
          status: "running",
          events: [
            event("inspect", 1, "Inspecting dataset", "completed"),
            event("plan", 2, "Planning analysis", "running"),
          ],
        });
      }
      return jsonResponse(COMPLETED);
    });
    renderWithQuery(<RunCard runId="run-1" onFollowUp={vi.fn()} />);

    expect(await screen.findByText("Planning analysis")).toBeInTheDocument();
    expect(screen.getByText("Analysing")).toBeInTheDocument();

    expect(await screen.findByText(/Revenue fell by/, {}, { timeout: 3000 })).toBeInTheDocument();
    expect(screen.queryByText("Analysing")).not.toBeInTheDocument();
    expect(screen.getByText("Change by region")).toBeInTheDocument();
    expect(screen.getByRole("group", { name: /Change by region/ })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Show the computed result r1" }));
    expect(await screen.findByRole("cell", { name: "West" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "-157,871.28" })).toBeInTheDocument();
  });

  it("shows a failed run's safe error", async () => {
    mockFetch(() =>
      jsonResponse({
        ...BASE,
        status: "failed",
        error_code: "llm_timeout",
        error_message: "The language model took too long to respond.",
        events: [event("plan", 1, "Planning analysis", "failed")],
      }),
    );
    renderWithQuery(<RunCard runId="run-1" onFollowUp={vi.fn()} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("took too long to respond");
  });

  it("cancels a running analysis", async () => {
    const fetchMock = mockFetch((request) =>
      request.method === "POST"
        ? jsonResponse({ ...BASE, status: "running", events: [] }, 202)
        : jsonResponse({ ...BASE, status: "running", events: [] }),
    );
    renderWithQuery(<RunCard runId="run-1" onFollowUp={vi.fn()} />);
    await userEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    await waitFor(() => {
      const posts = fetchMock.mock.calls
        .map((call) => call[0] as Request)
        .filter((r) => r.method === "POST");
      expect(posts.map((r) => new URL(r.url).pathname)).toEqual(["/api/analyses/run-1/cancel"]);
    });
  });

  it("downloads the report and a result's CSV from a finished analysis", async () => {
    const user = userEvent.setup();
    mockFetch(() => jsonResponse(COMPLETED));
    const urls = stubBlobUrls();
    const { blobs } = urls;
    const names: string[] = [];
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(function (this: HTMLAnchorElement) {
        names.push(this.download);
      });
    renderWithQuery(<RunCard runId="run-1" onFollowUp={vi.fn()} />);

    await user.click(
      await screen.findByRole("button", { name: "Download this analysis as a Markdown report" }),
    );
    expect(names).toEqual(["why-did-revenue-decrease-in-q3.md"]);
    expect(await blobs[0].text()).toContain("- West fell by $157,871. (evidence: r1)");

    await user.click(screen.getByRole("button", { name: /Sum of Revenue by Region/ }));
    await user.click(screen.getByRole("button", { name: "Download r1 as CSV (2 rows)" }));
    expect(names[1]).toBe("r1-sum-of-revenue-by-region.csv");
    expect(await blobs[1].text()).toContain("West,-157871.28");
    click.mockRestore();
    urls.restore();
  });

  it("offers no report while the analysis is running", async () => {
    mockFetch(() => jsonResponse({ ...BASE, status: "running", events: [] }));
    renderWithQuery(<RunCard runId="run-1" onFollowUp={vi.fn()} />);
    await screen.findByText("Analysing");
    expect(screen.queryByRole("button", { name: /Markdown report/ })).toBeNull();
  });

  it("scrolls to itself when a history link points at it", async () => {
    window.history.replaceState(null, "", "#run-run-1");
    const scroll = vi.spyOn(Element.prototype, "scrollIntoView");
    mockFetch(() => jsonResponse(COMPLETED));
    renderWithQuery(<RunCard runId="run-1" onFollowUp={vi.fn()} />);
    const heading = await screen.findByRole("heading", { name: BASE.question });
    await waitFor(() => expect(scroll.mock.contexts).toContain(heading.closest("article")));
    window.history.replaceState(null, "", "/");
  });

  it("stays on its question while content above it loads, until the reader scrolls", async () => {
    let resized: (() => void) | undefined;
    class FakeResizeObserver {
      constructor(callback: () => void) {
        resized = callback;
      }
      observe() {}
      disconnect() {
        resized = undefined; // a disconnected observer reports nothing more
      }
    }
    vi.stubGlobal("ResizeObserver", FakeResizeObserver);
    window.history.replaceState(null, "", "#run-run-1");
    const scroll = vi.spyOn(Element.prototype, "scrollIntoView");
    mockFetch(() => jsonResponse(COMPLETED));
    renderWithQuery(<RunCard runId="run-1" onFollowUp={vi.fn()} />);
    const heading = await screen.findByRole("heading", { name: BASE.question });
    const article = heading.closest("article");
    await waitFor(() => expect(scroll.mock.contexts).toContain(article));
    const before = scroll.mock.calls.length;
    resized?.(); // an earlier answer finished loading and grew
    expect(scroll.mock.calls.length).toBe(before + 1);
    window.dispatchEvent(new Event("wheel"));
    resized?.();
    expect(scroll.mock.calls.length).toBe(before + 1);
    window.history.replaceState(null, "", "/");
    vi.unstubAllGlobals();
  });

  it("keeps the activity on screen while updates are failing", async () => {
    let calls = 0;
    mockFetch(() =>
      ++calls === 1
        ? jsonResponse({
            ...BASE,
            status: "running",
            events: [event("plan", 1, "Planning analysis", "running")],
          })
        : new Response("down", { status: 503 }),
    );
    renderWithQuery(<RunCard runId="run-1" onFollowUp={vi.fn()} />);
    expect(await screen.findByText(/Reconnecting/, {}, { timeout: 3000 })).toBeInTheDocument();
    expect(screen.getByText("Planning analysis")).toBeInTheDocument();
  });
});
