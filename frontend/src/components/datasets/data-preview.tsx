"use client";

import { useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { type ColumnProfile, useDatasetPreview } from "@/lib/datasets/api";
import { formatCell, formatInteger } from "@/lib/format";

const PAGE_SIZE = 50;

export function DataPreview({ datasetId, columns }: { datasetId: string; columns: ColumnProfile[] }) {
  const [offset, setOffset] = useState(0);
  const preview = useDatasetPreview(datasetId, offset, PAGE_SIZE);
  const labels = new Map(columns.map((c) => [c.name, c.original_name]));
  const numeric = new Set(columns.filter((c) => c.semantic_type === "numeric").map((c) => c.name));

  if (preview.isPending) {
    return (
      <p className="flex items-center gap-2 text-sm text-slate">
        <Spinner size={14} label="" /> Loading rows…
      </p>
    );
  }
  if (preview.isError) {
    return (
      <Alert
        tone="danger"
        title="Rows couldn't be loaded"
        action={
          <Button variant="secondary" size="sm" onClick={() => preview.refetch()}>
            Try again
          </Button>
        }
      >
        {preview.error.message}
      </Alert>
    );
  }

  const { rows, total_rows: total } = preview.data;
  const first = total === 0 ? 0 : offset + 1;
  const last = Math.min(offset + rows.length, total);

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="tabular text-sm text-slate" aria-live="polite">
          Rows {formatInteger(first)} to {formatInteger(last)} of {formatInteger(total)}
        </p>
        <div className="flex gap-2">
          <Button
            variant="secondary"
            size="sm"
            disabled={offset === 0 || preview.isFetching}
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
          >
            Previous
          </Button>
          <Button
            variant="secondary"
            size="sm"
            disabled={last >= total || preview.isFetching}
            onClick={() => setOffset(offset + PAGE_SIZE)}
          >
            Next
          </Button>
        </div>
      </div>
      <div className="relative mt-3 max-h-[32rem] overflow-auto rounded-(--radius-panel) border border-rule bg-surface">
        <table className="w-full text-sm">
          <caption className="sr-only">Dataset rows</caption>
          <thead className="sticky top-0 bg-surface">
            <tr className="border-b border-rule text-left text-slate">
              <th scope="col" className="px-3 py-2 text-right font-medium">
                <span className="sr-only">Row number</span>
              </th>
              {preview.data.columns.map((column) => (
                <th
                  key={column}
                  scope="col"
                  className={`whitespace-nowrap px-3 py-2 font-medium ${numeric.has(column) ? "text-right" : ""}`}
                >
                  {labels.get(column) ?? column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-rule">
            {rows.map((row, rowIndex) => (
              <tr key={offset + rowIndex}>
                <td className="tabular px-3 py-1.5 text-right text-slate">
                  {formatInteger(offset + rowIndex + 1)}
                </td>
                {row.map((value, columnIndex) => {
                  const column = preview.data.columns[columnIndex];
                  return (
                    <td
                      key={column}
                      className={`max-w-72 truncate whitespace-nowrap px-3 py-1.5 ${numeric.has(column) ? "tabular text-right" : ""}`}
                      title={value === null ? "Missing" : String(value)}
                    >
                      {value === null ? <span className="text-slate/60">missing</span> : formatCell(value)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
