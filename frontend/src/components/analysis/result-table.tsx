import { clsx } from "clsx";

import type { StoredResult } from "@/lib/analyses/api";
import { formatCell, formatInteger } from "@/lib/format";

const MAX_ROWS = 100;

function isNumericColumn(rows: unknown[][], index: number): boolean {
  return rows.some((row) => typeof row[index] === "number") &&
    rows.every((row) => row[index] === null || typeof row[index] === "number");
}

function label(key: string): string {
  return key.replace(/_/g, " ");
}

export function ResultTable({ result, compact = false }: { result: StoredResult; compact?: boolean }) {
  const { columns, rows, row_count: count, truncated } = result.table;
  const shown = rows.slice(0, MAX_ROWS);
  const numeric = columns.map((_, index) => isNumericColumn(rows, index));
  const summary = Object.entries(result.summary ?? {});

  return (
    <div>
      {!compact && summary.length ? (
        <dl className="mb-3 flex flex-wrap gap-x-6 gap-y-1 text-sm">
          {summary.map(([key, value]) => (
            <div key={key} className="flex gap-1.5">
              <dt className="text-slate">{label(key)}</dt>
              <dd className="tabular">{value === null ? "—" : formatCell(value)}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      <div className="relative max-h-96 overflow-auto rounded-(--radius-control) border border-rule">
        <table className="w-full text-sm">
          <caption className="sr-only">{result.description}</caption>
          <thead className="sticky top-0 bg-paper">
            <tr className="text-left text-slate">
              {columns.map((column, index) => (
                <th
                  key={column.name}
                  scope="col"
                  className={clsx(
                    "whitespace-nowrap px-3 py-1.5 font-medium",
                    numeric[index] && "text-right",
                  )}
                >
                  {label(column.name)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-rule bg-surface">
            {shown.map((row, rowIndex) => (
              <tr key={rowIndex}>
                {row.map((value, index) => (
                  <td
                    key={columns[index]?.name ?? index}
                    className={clsx(
                      "max-w-72 truncate whitespace-nowrap px-3 py-1.5",
                      numeric[index] && "tabular text-right",
                    )}
                    title={value === null ? "Missing" : String(value)}
                  >
                    {value === null ? <span className="text-slate/60">—</span> : formatCell(value)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-1.5 text-sm text-slate">
        {formatInteger(Math.min(count, MAX_ROWS))} of {formatInteger(count)} row(s) shown
        {truncated ? "; the engine's row limit cut this result short" : ""}.
        {result.notes?.length ? ` ${result.notes.join(" ")}` : ""}
      </p>
      {result.sql ? (
        <details className="mt-1.5 text-sm">
          <summary className="cursor-pointer text-slate">SQL that ran</summary>
          <pre className="mt-1 overflow-x-auto rounded-(--radius-control) bg-paper p-2 text-[13px]">
            {result.sql}
          </pre>
        </details>
      ) : null}
    </div>
  );
}
