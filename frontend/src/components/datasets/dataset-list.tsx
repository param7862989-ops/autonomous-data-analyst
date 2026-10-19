"use client";

import Link from "next/link";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { useDatasets } from "@/lib/datasets/api";
import { formatBytes, formatDateTime, formatInteger } from "@/lib/format";

export function DatasetList() {
  const datasets = useDatasets();

  if (datasets.isPending) {
    return (
      <p className="flex items-center gap-2 text-sm text-slate">
        <Spinner size={14} label="" /> Loading your datasets…
      </p>
    );
  }
  if (datasets.isError) {
    return (
      <Alert
        tone="danger"
        title="Your datasets couldn't be loaded"
        action={
          <Button variant="secondary" size="sm" onClick={() => datasets.refetch()}>
            Try again
          </Button>
        }
      >
        {datasets.error.message}
      </Alert>
    );
  }
  if (datasets.data.items.length === 0) {
    return (
      <div className="rounded-(--radius-panel) border border-dashed border-rule-strong px-5 py-8 text-center">
        <p className="font-medium">No datasets yet</p>
        <p className="mt-1 text-sm text-slate">
          Upload a CSV or Excel file to see its profile and start asking questions.
        </p>
      </div>
    );
  }

  return (
    <div className="relative overflow-x-auto rounded-(--radius-panel) border border-rule bg-surface">
      <table className="w-full min-w-[36rem] text-sm">
        <caption className="sr-only">Your datasets</caption>
        <thead>
          <tr className="border-b border-rule text-left text-slate">
            <th scope="col" className="px-4 py-2.5 font-medium">
              Name
            </th>
            <th scope="col" className="px-4 py-2.5 text-right font-medium">
              Rows
            </th>
            <th scope="col" className="px-4 py-2.5 text-right font-medium">
              Columns
            </th>
            <th scope="col" className="px-4 py-2.5 text-right font-medium">
              File size
            </th>
            <th scope="col" className="px-4 py-2.5 font-medium">
              Uploaded
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-rule">
          {datasets.data.items.map((dataset) => (
            <tr key={dataset.id} className="hover:bg-paper">
              <td className="px-4 py-3">
                <Link
                  href={`/datasets/${dataset.id}`}
                  className="font-medium text-primary underline-offset-2 hover:underline"
                >
                  {dataset.name}
                </Link>
                <span className="block text-slate">
                  {dataset.original_filename}
                  {dataset.sheet_name ? `, sheet ${dataset.sheet_name}` : ""}
                </span>
              </td>
              <td className="tabular px-4 py-3 text-right">{formatInteger(dataset.row_count)}</td>
              <td className="tabular px-4 py-3 text-right">
                {formatInteger(dataset.column_count)}
              </td>
              <td className="tabular px-4 py-3 text-right">
                {formatBytes(dataset.upload_size_bytes)}
              </td>
              <td className="whitespace-nowrap px-4 py-3 text-slate">
                {formatDateTime(dataset.created_at)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
