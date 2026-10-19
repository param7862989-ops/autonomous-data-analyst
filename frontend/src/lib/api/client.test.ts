import { afterEach, describe, expect, it, vi } from "vitest";

import { jsonResponse, mockFetch } from "@/test/utils";

import { api, unwrap } from "./client";
import { ApiError } from "./errors";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("unwrap", () => {
  it("returns data for a successful response", async () => {
    mockFetch(() => jsonResponse({ status: "ok" }));
    await expect(unwrap(api.GET("/api/health"))).resolves.toEqual({ status: "ok" });
  });

  it("sends the CSRF header and same-origin credentials", async () => {
    const fetchMock = mockFetch(() => jsonResponse({ status: "ok" }));
    await unwrap(api.GET("/api/health"));
    const request = fetchMock.mock.calls[0][0] as Request;
    expect(request.headers.get("X-Requested-With")).toBe("fetch");
    expect(request.credentials).toBe("same-origin");
    expect(new URL(request.url).pathname).toBe("/api/health");
  });

  it("converts the backend error envelope into an ApiError", async () => {
    mockFetch(() =>
      jsonResponse(
        {
          error: {
            code: "not_found",
            message: "Dataset not found.",
            details: null,
            request_id: "abc123",
          },
        },
        404,
      ),
    );
    const error = await unwrap(api.GET("/api/health")).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      status: 404,
      code: "not_found",
      message: "Dataset not found.",
      requestId: "abc123",
    });
  });

  it("uses a safe fallback message for non-envelope errors", async () => {
    mockFetch(() => new Response("<html>Bad gateway</html>", { status: 502 }));
    const error = await unwrap(api.GET("/api/health")).catch((e: unknown) => e);
    expect(error).toMatchObject({ status: 502, code: "http_error" });
    expect((error as ApiError).message).not.toContain("html");
  });

  it("reports network failures as status 0", async () => {
    mockFetch(() => {
      throw new TypeError("Failed to fetch");
    });
    const error = await unwrap(api.GET("/api/health")).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).isNetworkError).toBe(true);
  });
});
