import { describe, expect, it } from "vitest";

import { loginPathFor, safeNextPath } from "./redirect";

describe("safeNextPath", () => {
  it("accepts same-origin absolute paths", () => {
    expect(safeNextPath("/datasets/abc?tab=profile")).toBe("/datasets/abc?tab=profile");
  });

  it.each([
    ["https://evil.example"],
    ["//evil.example"],
    ["/\\evil.example"],
    ["javascript:alert(1)"],
    ["datasets"],
    ["/\u0000//evil.example"],
    ["/login"],
    ["/register?next=/x"],
  ])("rejects %s", (value) => {
    expect(safeNextPath(value)).toBe("/");
  });

  it("falls back for empty values", () => {
    expect(safeNextPath(null)).toBe("/");
    expect(safeNextPath("", "/home")).toBe("/home");
  });
});

describe("loginPathFor", () => {
  it("encodes the current path as next", () => {
    expect(loginPathFor("/datasets/1")).toBe("/login?next=%2Fdatasets%2F1");
  });

  it("omits next for the home page", () => {
    expect(loginPathFor("/")).toBe("/login");
  });
});
