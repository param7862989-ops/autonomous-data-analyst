import { describe, expect, it } from "vitest";

import { ApiError } from "./api/errors";
import { shouldRetry } from "./query-client";

const err = (status: number) => new ApiError({ status, code: "x", message: "x" });

describe("shouldRetry", () => {
  it("retries network and server errors up to twice", () => {
    expect(shouldRetry(0, err(0))).toBe(true);
    expect(shouldRetry(1, err(503))).toBe(true);
    expect(shouldRetry(2, err(503))).toBe(false);
  });

  it("never retries client errors", () => {
    for (const status of [400, 401, 403, 404, 409, 422, 429]) {
      expect(shouldRetry(0, err(status))).toBe(false);
    }
  });

  it("does not retry unknown errors", () => {
    expect(shouldRetry(0, new Error("boom"))).toBe(false);
  });
});
