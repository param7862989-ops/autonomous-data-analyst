import type { Metadata } from "next";

import { ConversationList } from "@/components/analysis/conversation-list";
import { PageHeader } from "@/components/ui/page";

export const metadata: Metadata = { title: "Conversations" };

export default function ConversationsPage() {
  return (
    <div>
      <PageHeader
        title="Conversations"
        lead="A conversation is a run of questions about one dataset; follow-ups use the earlier answers as context. Open one to continue, rename or delete it."
      />
      <div className="mt-8 max-w-4xl">
        <ConversationList />
      </div>
    </div>
  );
}
