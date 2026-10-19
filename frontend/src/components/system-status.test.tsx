import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { jsonResponse, mockFetch, renderWithQuery } from "@/test/utils";

import { SystemStatus } from "./system-status";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("SystemStatus", () => {
  it("shows a loading state, then each readiness check", async () => {
    mockFetch(() =>
      jsonResponse({ status: "ready", checks: [{ name: "storage", ok: true }] }),
    );
    renderWithQuery(<SystemStatus />);
    expect(screen.getByText(/checking the api/i)).toBeInTheDocument();
    expect(await screen.findByText("File storage")).toBeInTheDocument();
    expect(screen.getByText("Responding")).toBeInTheDocument();
    expect(screen.getByText("Available")).toBeInTheDocument();
  });

  it("shows failing dependencies from a 503 readiness response", async () => {
    mockFetch(() =>
      jsonResponse(
        {
          status: "not_ready",
          checks: [
            { name: "storage", ok: true },
            { name: "database", ok: false },
          ],
        },
        503,
      ),
    );
    renderWithQuery(<SystemStatus />);
    expect(await screen.findByText("Database")).toBeInTheDocument();
    expect(screen.getByText("Unavailable")).toBeInTheDocument();
  });

  it("explains when the API cannot be reached", async () => {
    mockFetch(() => {
      throw new TypeError("Failed to fetch");
    });
    renderWithQuery(<SystemStatus />);
    expect(await screen.findByText(/unreachable/i)).toBeInTheDocument();
  });

  it("explains when the API answers with an unexpected error", async () => {
    mockFetch(() => new Response("Internal Server Error", { status: 500 }));
    renderWithQuery(<SystemStatus />);
    expect(await screen.findByText(/not responding/i)).toBeInTheDocument();
  });
});
