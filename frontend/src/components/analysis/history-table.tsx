"use client";

import { clsx } from "clsx";
import Link from "next/link";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { type RunStatus, useHistory } from "@/lib/analyses/api";
import { formatDateTime } from "@/lib/format";

const STATUS: Record<RunStatus, { label: string; tone: string }> = {
  queued: { label: "Queued", tone: "text-slate" },
  running: { label: "Running", tone: "text-primary" },
  completed: { label: "Answered", tone: "text-success" },
  failed: { label: "Failed", tone: "text-danger" },
  cancelled: { label: "Cancelled", tone: "text-slate" },
};

export function HistoryTable({ limit = 50, compact = false }: { limit?: number; compact?: boolean }) {
  const history = useHistory(undefined, limit);
  if (history.isPending) {
    return (
      <p className="flex items-center gap-2 text-sm text-slate">
        <Spinner size={14} label="" /> Loading history…
      </p>
    );
  }
  if (history.isError) {
    return (
      <Alert
        tone="danger"
        title="History couldn't be loaded"
        action={
          <Button variant="secondary" size="sm" onClick={() => history.refetch()}>
            Try again
          </Button>
        }
      >
        {history.error.message}
      </Alert>
    );
  }
  if (!history.data.items.length) {
    return (
      <p className="text-sm text-slate">
        No analyses yet. Open a dataset and ask a question to start.
      </p>
    );
  }
  return (
    <ul className="divide-y divide-rule rounded-(--radius-panel) border border-rule bg-surface">
      {history.data.items.map((item) => (
        <li key={item.id} className="px-4 py-3">
          <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
            <Link
              href={`/conversations/${item.conversation_id}#run-${item.id}`}
              className="min-w-0 font-medium text-primary underline-offset-2 hover:underline"
            >
              {item.question}
            </Link>
            <span className="flex gap-3 text-sm">
              <span className={clsx("font-medium", STATUS[item.status].tone)}>
                {STATUS[item.status].label}
              </span>
              <span className="text-slate">{formatDateTime(item.created_at)}</span>
            </span>
          </div>
          <p className="mt-0.5 text-sm text-slate">{item.dataset_name}</p>
          {!compact && item.answer_summary ? (
            <p className="mt-1.5 max-w-[75ch] font-serif text-[15px]">{item.answer_summary}</p>
          ) : null}
        </li>
      ))}
    </ul>
  );
}
