"use client";

import { MessageSquarePlus } from "lucide-react";
import { useRouter } from "next/navigation";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { useCreateConversation, useServerConfig } from "@/lib/analyses/api";

import { ConversationList } from "./conversation-list";

export function StartConversationButton({ datasetId }: { datasetId: string }) {
  const router = useRouter();
  const create = useCreateConversation();
  return (
    <div>
      <Button
        onClick={() =>
          create.mutate(datasetId, {
            onSuccess: (conversation) => router.push(`/conversations/${conversation.id}`),
          })
        }
        pending={create.isPending}
      >
        <MessageSquarePlus size={16} aria-hidden="true" />
        Ask a question
      </Button>
      {create.isError ? (
        <p className="mt-2 text-sm text-danger" role="alert">
          {create.error.message}
        </p>
      ) : null}
    </div>
  );
}

export function DatasetConversations({ datasetId }: { datasetId: string }) {
  const config = useServerConfig();
  return (
    <section aria-labelledby="conversations-heading">
      <h2 id="conversations-heading" className="text-base font-semibold">
        Conversations
      </h2>
      {config.data && !config.data.analysis_enabled ? (
        <Alert tone="info" className="mt-3">
          Asking questions is unavailable because this server has no language model configured.
        </Alert>
      ) : null}
      <div className="mt-3">
        <ConversationList key={datasetId} datasetId={datasetId} pageSize={10} />
      </div>
    </section>
  );
}
