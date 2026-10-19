import { screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { jsonResponse, mockFetch, renderWithQuery } from "@/test/utils";

import { RequireAuth } from "./require-auth";

const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
  usePathname: () => "/datasets/7",
}));

beforeEach(() => replace.mockReset());
afterEach(() => vi.unstubAllGlobals());

describe("RequireAuth", () => {
  it("renders children for a signed-in user", async () => {
    mockFetch(() =>
      jsonResponse({ id: "u1", email: "ana@example.com", created_at: "2026-10-19T00:00:00Z" }),
    );
    renderWithQuery(<RequireAuth>secret content</RequireAuth>);
    expect(screen.getByText(/checking your session/i)).toBeInTheDocument();
    expect(await screen.findByText("secret content")).toBeInTheDocument();
  });

  it("redirects to sign in with the current path when the session is missing", async () => {
    mockFetch(() =>
      jsonResponse(
        { error: { code: "not_authenticated", message: "Sign in", details: null, request_id: "r" } },
        401,
      ),
    );
    renderWithQuery(<RequireAuth>secret content</RequireAuth>);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login?next=%2Fdatasets%2F7"));
    expect(screen.queryByText("secret content")).not.toBeInTheDocument();
  });

  it("offers a retry when the session check fails for another reason", async () => {
    mockFetch(() => {
      throw new TypeError("Failed to fetch");
    });
    renderWithQuery(<RequireAuth>secret content</RequireAuth>);
    expect(await screen.findByRole("alert")).toHaveTextContent(/check your session/i);
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
  });
});
