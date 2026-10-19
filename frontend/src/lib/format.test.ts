import { describe, expect, it } from "vitest";

import { formatBytes, formatCell, formatNumber, formatPercent } from "./format";

describe("format helpers", () => {
  it("formats numbers for tables", () => {
    expect(formatNumber(1234.567)).toBe("1,234.57");
    expect(formatNumber(42)).toBe("42");
    expect(formatNumber(0.12345)).toBe("0.1235");
    expect(formatNumber(2_500_000)).toBe("2.5M");
    expect(formatNumber(null)).toBe("—");
    expect(formatNumber(Number.NaN)).toBe("—");
  });

  it("formats percentages", () => {
    expect(formatPercent(0.25)).toBe("25%");
    expect(formatPercent(0.1234)).toBe("12.3%");
    expect(formatPercent(0.0004)).toBe("<0.1%");
    expect(formatPercent(0)).toBe("0%");
  });

  it("formats byte sizes", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(2048)).toBe("2.0 KB");
    expect(formatBytes(25 * 1024 * 1024)).toBe("25 MB");
  });

  it("formats table cells", () => {
    expect(formatCell(null)).toBe("");
    expect(formatCell("2024-01-05T00:00:00")).toBe("2024-01-05");
    expect(formatCell("2024-01-05T10:30:00")).toBe("2024-01-05 10:30:00");
    expect(formatCell(true)).toBe("true");
    expect(formatCell("North")).toBe("North");
  });
});
