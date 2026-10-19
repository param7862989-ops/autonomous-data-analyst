import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ColumnProfile } from "@/lib/datasets/api";
import { jsonResponse, mockFetch, renderWithQuery } from "@/test/utils";

import { DataPreview } from "./data-preview";

afterEach(() => vi.unstubAllGlobals());

const COLUMNS = [
  { name: "region", original_name: "Region", semantic_type: "categorical" },
  { name: "revenue", original_name: "Revenue", semantic_type: "numeric" },
] as ColumnProfile[];

describe("DataPreview", () => {
  it("pages through rows using offsets", async () => {
    const fetchMock = mockFetch((request) => {
      const offset = Number(new URL(request.url).searchParams.get("offset"));
      return jsonResponse({
        columns: ["region", "revenue"],
        rows: [[offset === 0 ? "North" : "West", null]],
        offset,
        limit: 50,
        total_rows: 60,
      });
    });
    renderWithQuery(<DataPreview datasetId="d1" columns={COLUMNS} />);

    expect(await screen.findByText("North")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Revenue" })).toBeInTheDocument();
    expect(screen.getByText("missing")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();

    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByText("West")).toBeInTheDocument();
    await waitFor(() => {
      const urls = fetchMock.mock.calls.map((call) => (call[0] as Request).url);
      expect(urls.some((url) => url.includes("offset=50"))).toBe(true);
    });
  });
});
