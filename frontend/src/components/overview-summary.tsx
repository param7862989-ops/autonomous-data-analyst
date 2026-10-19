"use client";

import Link from "next/link";

import { HistoryTable } from "@/components/analysis/history-table";
import { useConversations, useHistory } from "@/lib/analyses/api";
import { useDatasets } from "@/lib/datasets/api";
import { formatInteger } from "@/lib/format";

/** Counts and recent activity for the signed-in user, all read from the API. */
export function OverviewSummary() {
  const datasets = useDatasets();
  const conversations = useConversations();
  const history = useHistory(undefined, 5);
  const facts = [
    { label: "Datasets", value: datasets.data?.total, href: "/datasets" },
    { label: "Conversations", value: conversations.data?.total, href: "/history" },
    { label: "Questions asked", value: history.data?.total, href: "/history" },
  ];
  const empty = datasets.data?.total === 0;

  return (
    <div className="space-y-10">
      <dl className="grid grid-cols-3 gap-x-8">
        {facts.map((fact) => (
          <div key={fact.label} className="border-l-2 border-rule-strong pl-3">
            <dt className="text-sm text-slate">{fact.label}</dt>
            <dd className="text-2xl font-semibold">
              <Link href={fact.href} className="hover:text-primary">
                {fact.value === undefined ? "–" : formatInteger(fact.value)}
              </Link>
            </dd>
          </div>
        ))}
      </dl>

      {empty ? (
        <div className="rounded-(--radius-panel) border border-dashed border-rule-strong px-5 py-6">
          <p className="font-medium">Start with a dataset</p>
          <p className="mt-1 text-sm text-slate">
            Upload a CSV or Excel file. You will see its profile right away, then you can ask
            questions about it.
          </p>
          <Link
            href="/datasets"
            className="mt-3 inline-flex h-10 items-center rounded-(--radius-control) bg-primary px-4 font-medium text-white hover:bg-primary-hover"
          >
            Upload a dataset
          </Link>
        </div>
      ) : (
        <section aria-labelledby="recent-heading">
          <div className="flex items-baseline justify-between">
            <h2 id="recent-heading" className="text-base font-semibold">
              Recent questions
            </h2>
            <Link href="/history" className="text-sm font-medium text-primary hover:underline">
              All history
            </Link>
          </div>
          <div className="mt-3">
            <HistoryTable limit={5} compact />
          </div>
        </section>
      )}
    </div>
  );
}
