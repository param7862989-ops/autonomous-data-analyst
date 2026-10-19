import { clsx } from "clsx";

import type { ColumnProfile } from "@/lib/datasets/api";
import { formatDataDate, formatInteger, formatNumber, formatPercent } from "@/lib/format";

import { MiniHistogram } from "./mini-histogram";
import { TypeBadge } from "./type-badge";

function Summary({ column }: { column: ColumnProfile }) {
  if (column.non_null_count === 0) return <span className="text-slate">No values</span>;
  if (column.numeric) {
    const { min, max, mean, median } = column.numeric;
    return (
      <dl className="tabular grid grid-cols-[auto_1fr] gap-x-2 text-slate">
        <dt>Range</dt>
        <dd className="text-ink">
          {formatNumber(min)} to {formatNumber(max)}
        </dd>
        <dt>Mean</dt>
        <dd className="text-ink">
          {formatNumber(mean)} <span className="text-slate">(median {formatNumber(median)})</span>
        </dd>
      </dl>
    );
  }
  if (column.datetime?.min && column.datetime.max) {
    return (
      <span className="tabular">
        {formatDataDate(column.datetime.min)} to {formatDataDate(column.datetime.max)}
      </span>
    );
  }
  if (column.semantic_type === "text" && column.top_values?.length) {
    // Free text rarely repeats; an example says more than a frequency table.
    return (
      <span className="block min-w-0 truncate" title={column.top_values[0].value}>
        <span className="text-slate">e.g. </span>
        {column.top_values[0].value}
      </span>
    );
  }
  if (column.top_values?.length) {
    const top = column.top_values.slice(0, 3);
    return (
      <ul className="space-y-0.5">
        {top.map((item) => (
          <li key={item.value} className="flex gap-2">
            <span className="min-w-0 truncate" title={item.value}>
              {item.value}
            </span>
            <span className="tabular shrink-0 text-slate">
              {formatPercent(item.count / column.non_null_count, 0)}
            </span>
          </li>
        ))}
      </ul>
    );
  }
  return null;
}

function MissingBar({ share }: { share: number }) {
  return (
    <div className="flex items-center gap-2">
      <span
        className={clsx("tabular w-12 text-right", share >= 0.5 ? "text-warning" : "text-ink")}
      >
        {formatPercent(share)}
      </span>
      <span aria-hidden="true" className="h-1.5 w-16 rounded-full bg-rule">
        <span
          className={clsx("block h-full rounded-full", share >= 0.5 ? "bg-warning" : "bg-slate")}
          style={{ width: `${Math.min(share, 1) * 100}%` }}
        />
      </span>
    </div>
  );
}

export function ProfileTable({ columns }: { columns: ColumnProfile[] }) {
  return (
    <div className="relative overflow-x-auto rounded-(--radius-panel) border border-rule bg-surface">
      <table className="w-full min-w-[52rem] text-sm">
        <caption className="sr-only">Column profile</caption>
        <thead>
          <tr className="border-b border-rule text-left text-slate">
            <th scope="col" className="px-4 py-2.5 font-medium">
              Column
            </th>
            <th scope="col" className="px-4 py-2.5 font-medium">
              Type
            </th>
            <th scope="col" className="px-4 py-2.5 font-medium">
              Missing
            </th>
            <th scope="col" className="px-4 py-2.5 text-right font-medium">
              Distinct
            </th>
            <th scope="col" className="px-4 py-2.5 font-medium">
              Summary
            </th>
            <th scope="col" className="px-4 py-2.5 font-medium">
              <span className="sr-only">Distribution</span>
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-rule align-top">
          {columns.map((column) => (
            <tr key={column.name}>
              <th scope="row" className="px-4 py-3 text-left font-normal">
                <span className="block font-medium">{column.original_name}</span>
                {column.original_name !== column.name ? (
                  <span className="block text-slate">
                    as <code className="text-[13px]">{column.name}</code>
                  </span>
                ) : null}
              </th>
              <td className="px-4 py-3">
                <TypeBadge type={column.semantic_type} />
              </td>
              <td className="px-4 py-3">
                <MissingBar share={column.missing_share} />
              </td>
              <td className="tabular px-4 py-3 text-right">
                {formatInteger(column.unique_count)}
              </td>
              <td className="max-w-64 px-4 py-3">
                <Summary column={column} />
              </td>
              <td className="px-4 py-3">
                {column.histogram && column.histogram.length > 0 ? (
                  <MiniHistogram bins={column.histogram} label={column.original_name} />
                ) : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
