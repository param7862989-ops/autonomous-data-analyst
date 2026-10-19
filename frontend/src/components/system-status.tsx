"use client";

import { useQuery } from "@tanstack/react-query";
import { clsx } from "clsx";

import { api } from "@/lib/api/client";
import { ApiError, networkError, toApiError } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

import { Button } from "./ui/button";
import { Spinner } from "./ui/spinner";

type Readiness = components["schemas"]["ReadinessResponse"];

const CHECK_LABELS: Record<string, string> = {
  storage: "File storage",
  database: "Database",
};

/** Readiness returns 503 with a normal body when a dependency is down, so read both. */
async function fetchReadiness(): Promise<Readiness> {
  let result;
  try {
    result = await api.GET("/api/health/ready");
  } catch {
    throw networkError();
  }
  if (result.data) return result.data;
  const body = result.error as unknown;
  if (body && typeof body === "object" && "checks" in body) return body as Readiness;
  throw toApiError(result.response.status, body);
}

export function SystemStatus() {
  const query = useQuery({
    queryKey: ["health", "ready"],
    queryFn: fetchReadiness,
    refetchInterval: 30_000,
    retry: false,
  });

  return (
    <section aria-labelledby="system-status-heading" className="max-w-xl">
      <div className="flex items-center justify-between gap-4">
        <h2 id="system-status-heading" className="text-base font-semibold">
          System status
        </h2>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => query.refetch()}
          pending={query.isFetching}
        >
          Check again
        </Button>
      </div>
      <div className="mt-3 rounded-(--radius-panel) border border-rule bg-surface">
        {query.isPending ? (
          <p className="flex items-center gap-2 px-4 py-3 text-sm text-slate">
            <Spinner size={14} label="" /> Checking the API…
          </p>
        ) : query.isError ? (
          <StatusRow ok={false} label="API">
            {query.error instanceof ApiError && query.error.isNetworkError
              ? "Unreachable. Check your network connection."
              : "Not responding. Start the backend and check again."}
          </StatusRow>
        ) : (
          <ul className="divide-y divide-rule">
            <StatusRow ok label="API" as="li">
              Responding
            </StatusRow>
            {query.data.checks.map((check) => (
              <StatusRow key={check.name} ok={check.ok} label={CHECK_LABELS[check.name] ?? check.name} as="li">
                {check.ok ? "Available" : "Unavailable"}
              </StatusRow>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

function StatusRow({
  ok,
  label,
  children,
  as: Tag = "p",
}: {
  ok: boolean;
  label: string;
  children: React.ReactNode;
  as?: "p" | "li";
}) {
  return (
    <Tag className="flex items-center justify-between gap-4 px-4 py-3 text-sm">
      <span className="flex items-center gap-2.5">
        <span
          aria-hidden="true"
          className={clsx("size-2 rounded-full", ok ? "bg-success" : "bg-danger")}
        />
        {label}
      </span>
      <span className={clsx(ok ? "text-slate" : "font-medium text-danger")}>{children}</span>
    </Tag>
  );
}
