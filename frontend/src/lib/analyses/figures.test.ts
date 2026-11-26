import { describe, expect, it } from "vitest";

import { namesWithDigits, splitFigures } from "./figures";

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

  it("skips dates written with month names, as the backend does", () => {
    expect(figures("From April 1, 2024 to June 30, 2024, or 30 June and Sept. 15th.")).toEqual([]);
    expect(figures("June 30% growth")).toEqual([["30%", "verified"]]);
  });

  it("flags figures the grounding check could not verify", () => {
    expect(figures("West lost $63,359 and 99.9% of orders.", ["99.9%"])).toEqual([
      ["$63,359", "verified"],
      ["99.9%", "unverified"],
    ]);
  });

  it("leaves digits inside names from the results alone", () => {
    const names = namesWithDigits([{ table: { rows: [["Monitor 27in", 22795.87], ["$5M", "Model 300"]] } }]);
    expect(names).toEqual(["Monitor 27in", "Model 300"]);
    const shown = splitFigures("Monitor 27in fell 22,795.87; Model 3000 fell 27%.", [], names);
    expect(shown.filter((s) => s.figure).map((s) => s.text)).toEqual(["22,795.87", "3000", "27%"]);
  });

  it("keeps the full text when segments are joined", () => {
    const text = "Change of -12.3 percent in 2024-Q3 for West.";
    expect(splitFigures(text, []).map((s) => s.text).join("")).toBe(text);
  });
});
