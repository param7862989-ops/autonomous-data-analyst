import { AlertTriangle, Info } from "lucide-react";

import type { ColumnProfile, DataQualityWarning } from "@/lib/datasets/api";

export function QualityWarnings({
  warnings,
  columns,
}: {
  warnings: DataQualityWarning[];
  columns: ColumnProfile[];
}) {
  const displayName = new Map(columns.map((c) => [c.name, c.original_name]));
  const sorted = [...warnings].sort(
    (a, b) => Number(b.severity === "warning") - Number(a.severity === "warning"),
  );

  return (
    <section aria-labelledby="quality-heading">
      <h2 id="quality-heading" className="text-base font-semibold">
        Data quality
      </h2>
      {sorted.length === 0 ? (
        <p className="mt-2 text-sm text-slate">
          No issues found: no duplicate rows, heavily missing columns or unreadable values.
        </p>
      ) : (
        <ul className="mt-3 divide-y divide-rule rounded-(--radius-panel) border border-rule bg-surface">
          {sorted.map((warning, index) => {
            const Icon = warning.severity === "warning" ? AlertTriangle : Info;
            return (
              <li key={`${warning.code}-${warning.column}-${index}`} className="flex gap-3 px-4 py-2.5 text-sm">
                <Icon
                  size={16}
                  aria-label={warning.severity === "warning" ? "Warning" : "Note"}
                  className={
                    warning.severity === "warning" ? "mt-0.5 shrink-0 text-warning" : "mt-0.5 shrink-0 text-slate"
                  }
                />
                <span>
                  {warning.column ? (
                    <span className="font-medium">
                      {displayName.get(warning.column) ?? warning.column}:{" "}
                    </span>
                  ) : null}
                  {warning.message}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
