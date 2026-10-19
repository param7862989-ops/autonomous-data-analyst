import { describe, expect, it } from "vitest";

import { splitFigures } from "./figures";

const figures = (text: string, unverified: string[] = []) =>
  splitFigures(text, unverified)
    .filter((s) => s.figure)
    .map((s) => [s.text.trim(), s.figure]);

describe("splitFigures", () => {
  it("finds money, percentages and compact figures", () => {
    expect(figures("Revenue fell 34.5% to $255,612, about $0.26M.")).toEqual([
      ["34.5%", "verified"],
      ["$255,612", "verified"],
      ["$0.26M", "verified"],
    ]);
  });

  it("skips dates, quarters, ids, years and small counts", () => {
    expect(figures("In Q3 2024 (2024-07-01 to 2024-09-30) the top 3 regions, see r1 and c2.")).toEqual(
      [],
    );
  });

  it("flags figures the grounding check could not verify", () => {
    expect(figures("West lost $63,359 and 99.9% of orders.", ["99.9%"])).toEqual([
      ["$63,359", "verified"],
      ["99.9%", "unverified"],
    ]);
  });

  it("keeps the full text when segments are joined", () => {
    const text = "Change of -12.3 percent in 2024-Q3 for West.";
    expect(splitFigures(text, []).map((s) => s.text).join("")).toBe(text);
  });
});
