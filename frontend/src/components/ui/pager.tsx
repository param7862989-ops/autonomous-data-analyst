import { Button } from "@/components/ui/button";
import { formatInteger } from "@/lib/format";

/** Previous/next controls for an offset-paginated list; renders nothing when all items fit. */
export function Pager({
  label,
  offset,
  count,
  pageSize,
  total,
  busy = false,
  onChange,
}: {
  label: string;
  offset: number;
  /** Items on the current page. */
  count: number;
  pageSize: number;
  total: number;
  busy?: boolean;
  onChange: (offset: number) => void;
}) {
  if (offset === 0 && total <= pageSize) return null;
  return (
    <nav aria-label={label} className="mt-3 flex flex-wrap items-center justify-between gap-3">
      <p className="tabular text-sm text-slate" aria-live="polite">
        {count
          ? `${formatInteger(offset + 1)} to ${formatInteger(offset + count)} of ${formatInteger(total)}`
          : "Nothing on this page"}
      </p>
      <div className="flex gap-2">
        <Button
          variant="secondary"
          size="sm"
          disabled={offset === 0 || busy}
          onClick={() => onChange(Math.max(0, offset - pageSize))}
        >
          Previous
        </Button>
        <Button
          variant="secondary"
          size="sm"
          disabled={offset + count >= total || busy}
          onClick={() => onChange(offset + pageSize)}
        >
          Next
        </Button>
      </div>
    </nav>
  );
}
