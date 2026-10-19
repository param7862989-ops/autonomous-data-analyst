import { clsx } from "clsx";
import { Check, X } from "lucide-react";

import { Spinner } from "@/components/ui/spinner";
import type { ActivityEvent } from "@/lib/analyses/api";

function StatusIcon({ status }: { status: ActivityEvent["status"] }) {
  if (status === "running") return <Spinner size={14} label="In progress" className="text-primary" />;
  if (status === "failed") {
    return <X size={14} aria-label="Failed" className="text-danger" strokeWidth={2.5} />;
  }
  return <Check size={14} aria-label="Done" className="text-success" strokeWidth={2.5} />;
}

/** The steps an analysis actually performed, as reported by the backend. */
export function ActivityTimeline({ events, live }: { events: ActivityEvent[]; live: boolean }) {
  const ordered = [...events].sort((a, b) => a.seq - b.seq);
  if (!ordered.length) {
    return (
      <p className="flex items-center gap-2 text-sm text-slate">
        <Spinner size={14} label="" /> Waiting to start…
      </p>
    );
  }
  return (
    <ol aria-live={live ? "polite" : undefined} className="space-y-1.5">
      {ordered.map((event) => (
        <li key={event.key} className="flex gap-2.5 text-sm">
          <span className="mt-[3px] flex size-4 shrink-0 items-center justify-center">
            <StatusIcon status={event.status} />
          </span>
          <span className="min-w-0">
            <span className={clsx(event.status === "failed" && "text-danger")}>{event.label}</span>
            {event.detail ? (
              <span className="block break-words text-slate">{event.detail}</span>
            ) : null}
          </span>
        </li>
      ))}
    </ol>
  );
}
