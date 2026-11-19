import { describe, expect, it, vi } from "vitest";

import { stubBlobUrls } from "@/test/blob-urls";

import type { RunDetail, StoredResult } from "./api";
import { csvCell, downloadFile, resultToCsv, runToMarkdown, safeFilename } from "./export";

function result(overrides: Partial<StoredResult> = {}): StoredResult {
  return {
    id: "r1",
    tool: "execute_sql",
    operation: "sql",
    description: "Revenue by region",
    table: {
      columns: [
        { name: "region", type: "VARCHAR" },
        { name: "revenue", type: "DOUBLE" },
      ],
      rows: [
        ["West", -157871.28],
        ["East, North", 17306],
        [null, 0],
      ],
      row_count: 3,
      truncated: false,
    },
    summary: {},
    notes: [],
    sql: "SELECT region, SUM(revenue) FROM data GROUP BY 1",
    arguments: null,
    ...overrides,
  };
}

describe("CSV export", () => {
  it("quotes per RFC 4180 and writes every row with a BOM", () => {
    expect(resultToCsv(result())).toBe(
      '\uFEFFregion,revenue\r\nWest,-157871.28\r\n"East, North",17306\r\n,0\r\n',
    );
    expect(csvCell('say "hi"')).toBe('"say ""hi"""');
    expect(csvCell("two\nlines")).toBe('"two\nlines"');
    expect(csvCell(true)).toBe("true");
  });

  it("neutralises spreadsheet formulas in text but keeps real numbers", () => {
    expect(csvCell('=HYPERLINK("http://x","y")')).toBe(`"'=HYPERLINK(""http://x"",""y"")"`);
    expect(csvCell("+1")).toBe("'+1");
    expect(csvCell("-2")).toBe("'-2");
    expect(csvCell("@SUM(A1)")).toBe("'@SUM(A1)");
    expect(csvCell("\tcmd")).toBe("'\tcmd");
    expect(csvCell(-5)).toBe("-5");
  });
});

const RUN = {
  id: "run-1",
  conversation_id: "c",
  dataset_id: "d",
  question: "Why did revenue | fall?",
  status: "completed",
  stop_reason: "completed",
  answer_summary: null,
  created_at: "2026-11-19T10:00:00Z",
  finished_at: null,
  error_code: null,
  error_message: null,
  model: "gemini-3.8-flash",
  cancel_requested: false,
  started_at: null,
  events: [],
  outcome: {
    status: "completed",
    stop_reason: "completed",
    plan: { interpretation: "Q3 means Q3 2024." },
    answer: {
      summary: "Revenue fell 34%.",
      findings: [
        { statement: "West fell most.", kind: "fact", evidence: ["r1"] },
        { statement: "Maybe <b>seasonality</b>.", kind: "hypothesis", evidence: [] },
      ],
      caveats: ["Only two years of data."],
      chart_ids: [],
      follow_up_questions: [],
    },
    results: [result()],
    charts: [],
    grounding: {
      checked_numbers: 1,
      unverified_numbers: ["12"],
      invalid_references: [],
      unsupported_facts: [],
    },
    error_code: null,
    error_message: null,
    iterations: 1,
    tool_calls: 1,
    usage: {},
  },
} as unknown as RunDetail;

describe("Markdown report", () => {
  it("contains the answer, evidence, interpretation, tables and SQL", () => {
    const report = runToMarkdown(RUN, "sales.csv");
    expect(report).toContain("# Why did revenue \\| fall?");
    expect(report).toContain("Dataset: sales.csv");
    expect(report).toContain("Model: gemini-3.8-flash");
    expect(report).toContain("## What the data shows\n\n- West fell most. (evidence: r1)");
    expect(report).toContain("## Possible explanations, not proven by the data");
    expect(report).toContain("could not be matched to a computed result: 12");
    expect(report).toContain("- Only two years of data.");
    expect(report).toContain("Q3 means Q3 2024.");
    expect(report).toContain("| region | revenue |");
    expect(report).toContain("| East, North | 17306 |");
    expect(report).toContain("```sql\nSELECT region");
  });

  it("escapes markup from model and data text", () => {
    const report = runToMarkdown(RUN);
    expect(report).toContain("Maybe \\<b\\>seasonality\\</b\\>.");
    expect(report).not.toContain("<b>");
  });

  it("caps report tables and points to the CSV", () => {
    const rows = Array.from({ length: 60 }, (_, i) => [`r${i}`, i]);
    const big = result({ table: { ...result().table, rows, row_count: 60 } });
    const report = runToMarkdown({ ...RUN, outcome: { ...RUN.outcome!, results: [big] } });
    expect(report).toContain("| r49 | 49 |");
    expect(report).not.toContain("| r50 | 50 |");
    expect(report).toContain("First 50 of 60 rows");
  });
});

describe("files", () => {
  it("makes safe file names", () => {
    expect(safeFilename("Why did revenue decrease in Q3?", "md")).toBe(
      "why-did-revenue-decrease-in-q3.md",
    );
    expect(safeFilename("../../etc/passwd", "csv")).toBe("etcpasswd.csv");
    expect(safeFilename("???", "csv")).toBe("export.csv");
  });

  it("downloads through a temporary object URL", () => {
    const urls = stubBlobUrls();
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    vi.useFakeTimers();
    downloadFile("a.csv", "x", "text/csv");
    expect(click).toHaveBeenCalledOnce();
    expect(document.querySelector("a[download]")).toBeNull();
    vi.runAllTimers();
    expect(urls.blobs).toHaveLength(1);
    expect(urls.revoke).toHaveBeenCalledWith("blob:test-1");
    vi.useRealTimers();
    click.mockRestore();
    urls.restore();
  });
});
