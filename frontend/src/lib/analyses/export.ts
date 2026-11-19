import type { RunDetail, StoredResult } from "./api";

/**
 * Client-side exports. Everything exported is already in the run the browser loaded (each
 * result holds at most the engine's row cap), so there is no export endpoint to secure.
 */

type Cell = string | number | boolean | null;

// A spreadsheet treats a cell starting with one of these as a formula. Uploaded data is not
// trusted, so `=HYPERLINK("http://evil", "x")` in a cell must stay text when the CSV is opened
// (OWASP "CSV injection"). Prefixing an apostrophe makes Excel, LibreOffice and Google Sheets
// show the value as text. Only strings are touched: real numbers such as -5 stay numbers.
const FORMULA_START = /^[=+\-@\t\r]/;

export function csvCell(value: Cell): string {
  if (value === null) return "";
  let text = String(value);
  if (typeof value === "string" && FORMULA_START.test(text)) text = `'${text}`;
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

/** RFC 4180 CSV with a UTF-8 byte order mark, so Excel reads non-ASCII text correctly. */
export function resultToCsv(result: StoredResult): string {
  const { columns, rows } = result.table;
  const lines = [columns.map((c) => csvCell(c.name)), ...rows.map((row) => row.map(csvCell))];
  return `﻿${lines.map((cells) => cells.join(",")).join("\r\n")}\r\n`;
}

// --- Markdown report -----------------------------------------------------------------------

const REPORT_TABLE_ROWS = 50;

function mdText(text: string): string {
  // Keep model and data text from creating Markdown structure (tables, links, HTML).
  return text
    .replace(/\r?\n/g, " ")
    .replace(/([\\`*_[\]<>|])/g, "\\$1")
    .replace(/^([#>+-])/, "\\$1");
}

function mdTable(result: StoredResult): string[] {
  const { columns, rows, row_count: count } = result.table;
  if (!columns.length) return ["_No rows._"];
  const cell = (value: Cell) => (value === null ? "" : mdText(String(value)));
  const lines = [
    `| ${columns.map((c) => mdText(c.name)).join(" | ")} |`,
    `| ${columns.map(() => "---").join(" | ")} |`,
    ...rows.slice(0, REPORT_TABLE_ROWS).map((row) => `| ${row.map(cell).join(" | ")} |`),
  ];
  if (count > REPORT_TABLE_ROWS) {
    lines.push("", `_First ${REPORT_TABLE_ROWS} of ${count} rows; download the CSV for all of them._`);
  }
  return lines;
}

export function runToMarkdown(run: RunDetail, datasetName?: string): string {
  const outcome = run.outcome;
  const answer = outcome?.answer;
  const lines: string[] = [`# ${mdText(run.question)}`, ""];
  const meta = [
    datasetName ? `Dataset: ${mdText(datasetName)}` : null,
    `Asked: ${run.created_at}`,
    run.model ? `Model: ${mdText(run.model)}` : null,
    `Status: ${run.status}${run.stop_reason ? ` (${run.stop_reason})` : ""}`,
  ].filter(Boolean);
  lines.push(meta.join("  \n"), "");

  if (answer) {
    lines.push("## Answer", "", mdText(answer.summary), "");
    const unverified = outcome?.grounding?.unverified_numbers ?? [];
    if (unverified.length) {
      lines.push(
        `> Figures that could not be matched to a computed result: ${unverified.map(mdText).join(", ")}`,
        "",
      );
    }
    const section = (title: string, kind: "fact" | "hypothesis") => {
      const findings = answer.findings.filter((f) => f.kind === kind);
      if (!findings.length) return;
      lines.push(`## ${title}`, "");
      for (const f of findings) {
        const evidence = f.evidence.length ? ` (evidence: ${f.evidence.map(mdText).join(", ")})` : "";
        lines.push(`- ${mdText(f.statement)}${evidence}`);
      }
      lines.push("");
    };
    section("What the data shows", "fact");
    section("Possible explanations, not proven by the data", "hypothesis");
    if (answer.caveats.length) {
      lines.push("## Caveats", "", ...answer.caveats.map((c) => `- ${mdText(c)}`), "");
    }
  } else if (run.error_message) {
    lines.push("## Error", "", mdText(run.error_message), "");
  }

  if (outcome?.plan?.interpretation) {
    lines.push("## Interpretation", "", mdText(outcome.plan.interpretation), "");
  }

  if (outcome?.results.length) {
    lines.push("## Computed results", "");
    for (const result of outcome.results) {
      lines.push(`### ${mdText(result.id)}: ${mdText(result.description)}`, "");
      lines.push(...mdTable(result), "");
      if (result.sql) {
        // A fence longer than any backtick run inside the SQL cannot be closed early.
        const longest = Math.max(2, ...(result.sql.match(/`+/g) ?? []).map((m) => m.length));
        const fence = "`".repeat(longest + 1);
        lines.push(`${fence}sql`, result.sql, fence, "");
      }
    }
  }
  return `${lines.join("\n").trimEnd()}\n`;
}

// --- Files ---------------------------------------------------------------------------------

export function safeFilename(text: string, extension: string): string {
  const base =
    text
      .normalize("NFKD")
      .replace(/[^\w\s-]/g, "")
      .trim()
      .replace(/[\s_-]+/g, "-")
      .slice(0, 60)
      .replace(/-+$/, "")
      .toLowerCase() || "export";
  return `${base}.${extension}`;
}

export function downloadFile(filename: string, content: string, type: string): void {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.rel = "noopener";
  document.body.append(link);
  link.click();
  link.remove();
  // Revoke after the click has been handled; revoking synchronously can cancel the download.
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
