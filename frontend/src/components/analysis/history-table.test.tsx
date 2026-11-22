import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { jsonResponse, mockFetch, renderWithQuery } from "@/test/utils";

import { HistoryTable } from "./history-table";

afterEach(() => vi.unstubAllGlobals());

const item = (n: number) => ({
  id: `run-${n}`,
  conversation_id: "c1",
  dataset_id: "d1",
  dataset_name: "Sales",
  question: `Question ${n}`,
  status: "completed",
  stop_reason: "completed",
  answer_summary: null,
  created_at: "2026-11-22T10:00:00Z",
  finished_at: "2026-11-22T10:01:00Z",
});

function serve() {
  mockFetch((request) => {
    const offset = Number(new URL(request.url).searchParams.get("offset"));
    const items = [1, 2, 3].map(item).slice(offset, offset + 2);
    return jsonResponse({ items, total: 3, limit: 2, offset });
  });
}

describe("HistoryTable", () => {
  it("links to the question inside its conversation and pages to older ones", async () => {
    serve();
    renderWithQuery(<HistoryTable limit={2} />);
    const first = await screen.findByRole("link", { name: "Question 1" });
    expect(first).toHaveAttribute("href", "/conversations/c1#run-run-1");
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByRole("link", { name: "Question 3" })).toBeInTheDocument();
  });

  it("has no pager in the compact overview", async () => {
    serve();
    renderWithQuery(<HistoryTable limit={2} compact />);
    await screen.findByRole("link", { name: "Question 1" });
    expect(screen.queryByRole("navigation")).toBeNull();
  });
});
