import type { Metadata } from "next";

import { HistoryTable } from "@/components/analysis/history-table";
import { PageHeader } from "@/components/ui/page";

export const metadata: Metadata = { title: "History" };

export default function HistoryPage() {
  return (
    <div>
      <PageHeader
        title="History"
        lead="Every question you have asked, newest first. Open one to see its answer, its charts and the computations behind it."
      />
      <div className="mt-8 max-w-4xl">
        <HistoryTable />
      </div>
    </div>
  );
}
