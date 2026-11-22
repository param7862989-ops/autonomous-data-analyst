import type { Metadata } from "next";

import { ConversationList } from "@/components/analysis/conversation-list";

export const metadata: Metadata = { title: "Conversations" };

export default function ConversationsPage() {
  return (
    <div className="max-w-4xl">
      <h1 className="text-2xl font-semibold tracking-tight">Conversations</h1>
      <p className="mt-2 max-w-[65ch] text-slate">
        Each conversation is about one dataset and keeps the context for follow-up questions.
        Open one to continue, rename or delete it.
      </p>
      <div className="mt-8">
        <ConversationList />
      </div>
    </div>
  );
}
