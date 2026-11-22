import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { jsonResponse, mockFetch, renderWithQuery } from "@/test/utils";

import { ConversationList } from "./conversation-list";

afterEach(() => vi.unstubAllGlobals());

const item = (n: number) => ({
  id: `c${n}`,
  dataset_id: "d1",
  dataset_name: "Sales",
  title: `Conversation ${n}`,
  run_count: n,
  created_at: "2026-11-22T10:00:00Z",
  updated_at: "2026-11-22T10:00:00Z",
});

describe("ConversationList", () => {
  it("shows an empty state", async () => {
    mockFetch(() => jsonResponse({ items: [], total: 0, limit: 25, offset: 0 }));
    renderWithQuery(<ConversationList />);
    expect(await screen.findByText(/No conversations yet/)).toBeInTheDocument();
    expect(screen.queryByRole("navigation")).toBeNull();
  });

  it("links to each conversation and pages through them", async () => {
    const all = [1, 2, 3].map(item);
    mockFetch((request) => {
      const offset = Number(new URL(request.url).searchParams.get("offset"));
      return jsonResponse({ items: all.slice(offset, offset + 2), total: 3, limit: 2, offset });
    });
    renderWithQuery(<ConversationList pageSize={2} />);

    const first = await screen.findByRole("link", { name: "Conversation 1" });
    expect(first).toHaveAttribute("href", "/conversations/c1");
    expect(screen.getByText("1 to 2 of 3")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();

    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByRole("link", { name: "Conversation 3" })).toBeInTheDocument();
    expect(screen.getByText("3 to 3 of 3")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
  });

  it("lists only the given dataset's conversations", async () => {
    let asked: string | null = null;
    mockFetch((request) => {
      asked = new URL(request.url).searchParams.get("dataset_id");
      return jsonResponse({ items: [item(1)], total: 1, limit: 10, offset: 0 });
    });
    renderWithQuery(<ConversationList datasetId="d1" pageSize={10} />);
    await screen.findByRole("link", { name: "Conversation 1" });
    expect(asked).toBe("d1");
  });

  it("offers a retry after a failure", async () => {
    let calls = 0;
    mockFetch(() =>
      ++calls === 1
        ? new Response("boom", { status: 500 })
        : jsonResponse({ items: [item(1)], total: 1, limit: 25, offset: 0 }),
    );
    renderWithQuery(<ConversationList />);
    await userEvent.click(await screen.findByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("link", { name: "Conversation 1" })).toBeInTheDocument();
  });
});
