import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { jsonResponse, mockFetch, renderWithQuery } from "@/test/utils";

import { DatasetList } from "./dataset-list";

afterEach(() => vi.unstubAllGlobals());

const ITEM = {
  id: "d1",
  name: "Sales",
  original_filename: "sales.csv",
  file_format: "csv",
  sheet_name: null,
  upload_size_bytes: 602348,
  row_count: 7620,
  column_count: 10,
  created_at: "2026-10-19T10:00:00Z",
};

describe("DatasetList", () => {
  it("shows an empty state", async () => {
    mockFetch(() => jsonResponse({ items: [], total: 0, limit: 100, offset: 0 }));
    renderWithQuery(<DatasetList />);
    expect(await screen.findByText("No datasets yet")).toBeInTheDocument();
  });

  it("lists datasets with links and real counts", async () => {
    mockFetch(() => jsonResponse({ items: [ITEM], total: 1, limit: 100, offset: 0 }));
    renderWithQuery(<DatasetList />);
    const link = await screen.findByRole("link", { name: "Sales" });
    expect(link).toHaveAttribute("href", "/datasets/d1");
    expect(screen.getByText("7,620")).toBeInTheDocument();
    expect(screen.getByText("588 KB")).toBeInTheDocument();
  });

  it("offers a retry after a failure", async () => {
    let calls = 0;
    mockFetch(() => {
      calls += 1;
      return calls === 1
        ? new Response("boom", { status: 500 })
        : jsonResponse({ items: [ITEM], total: 1, limit: 100, offset: 0 });
    });
    renderWithQuery(<DatasetList />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/couldn't be loaded/);
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("link", { name: "Sales" })).toBeInTheDocument();
  });
});
