"use client";

import { clsx } from "clsx";
import Link from "next/link";
import { useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Pager } from "@/components/ui/pager";
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

export function HistoryTable({ limit = 25, compact = false }: { limit?: number; compact?: boolean }) {
  const [offset, setOffset] = useState(0);
  const history = useHistory(undefined, limit, offset);
  if (history.isPending) {
    return (
      <p className="flex items-center gap-2 text-sm text-slate">
        <Spinner size={14} label="" /> Loading history…
      </p>
    );
  }
  if (!history.data) {
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
        {history.error?.message}
      </Alert>
    );
  }
  if (!history.data.items.length && offset === 0) {
    return (
      <p className="text-sm text-slate">
        No analyses yet. Open a dataset and ask a question to start.
      </p>
    );
  }
  return (
    <>
      <ul className="divide-y divide-rule border-y border-rule">
        {history.data.items.map((item) => (
          <li key={item.id} className="py-3">
            <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
              <Link
                href={`/conversations/${item.conversation_id}#run-${item.id}`}
                className="min-w-0 font-serif text-[17px] font-semibold text-ink underline decoration-rule-strong underline-offset-4 hover:decoration-ink"
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
              <p className="mt-1.5 max-w-[72ch] text-[15px] text-ink/90">{item.answer_summary}</p>
            ) : null}
          </li>
        ))}
      </ul>
      {compact ? null : (
        <Pager
          label="History pages"
          offset={offset}
          count={history.data.items.length}
          pageSize={limit}
          total={history.data.total}
          busy={history.isPlaceholderData}
          onChange={setOffset}
        />
      )}
    </>
  );
}
