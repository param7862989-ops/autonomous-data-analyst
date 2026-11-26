"use client";

import Link from "next/link";

import { HistoryTable } from "@/components/analysis/history-table";
import { useConversations, useHistory } from "@/lib/analyses/api";
import { useDatasets } from "@/lib/datasets/api";
import { formatInteger } from "@/lib/format";

function plural(count: number, one: string, many: string): string {
  return `${formatInteger(count)} ${count === 1 ? one : many}`;
}

/** What the signed-in user has so far, as one sentence, each count linking to its list. */
export function OverviewCounts() {
  const datasets = useDatasets();
  const conversations = useConversations(undefined, 1);
  const history = useHistory(undefined, 1);
  const counts = [datasets.data?.total, conversations.data?.total, history.data?.total];
  if (counts.some((count) => count === undefined)) {
    return <p>Ask questions about your data in plain language and check every figure.</p>;
  }
  const [d, c, q] = counts as number[];
  if (d === 0) {
    return (
      <p>
        Nothing uploaded yet. Start with a spreadsheet: you will see its profile straight away,
        then you can ask questions about it.
      </p>
    );
  }
  const link = "text-ink underline decoration-rule-strong underline-offset-4 hover:decoration-ink";
  return (
    <p>
      You have{" "}
      <Link href="/datasets" className={link}>
        {plural(d, "dataset", "datasets")}
      </Link>
      ,{" "}
      <Link href="/conversations" className={link}>
        {plural(c, "conversation", "conversations")}
      </Link>{" "}
      and{" "}
      <Link href="/history" className={link}>
        {plural(q, "question", "questions")}
      </Link>{" "}
      asked so far.
    </p>
  );
}

export function RecentQuestions() {
  return <HistoryTable limit={5} compact />;
}
