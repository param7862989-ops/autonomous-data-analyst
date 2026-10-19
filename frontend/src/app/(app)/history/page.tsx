import type { Metadata } from "next";

import { HistoryTable } from "@/components/analysis/history-table";

export const metadata: Metadata = { title: "History" };

export default function HistoryPage() {
  return (
    <div className="max-w-4xl">
      <h1 className="text-2xl font-semibold tracking-tight">History</h1>
      <p className="mt-2 max-w-[65ch] text-slate">
        Every question you have asked, newest first. Open one to see its answer, charts and the
        computations behind it.
      </p>
      <div className="mt-8">
        <HistoryTable limit={100} />
      </div>
    </div>
  );
}
