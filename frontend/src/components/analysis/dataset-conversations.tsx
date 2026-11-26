"use client";

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

/** This dataset's conversations; the page supplies the heading. */
export function DatasetConversations({ datasetId }: { datasetId: string }) {
  const config = useServerConfig();
  return (
    <div>
      {config.data && !config.data.analysis_enabled ? (
        <Alert tone="info" className="mb-3">
          Asking questions is unavailable because this server has no language model configured.
        </Alert>
      ) : null}
      <ConversationList key={datasetId} datasetId={datasetId} pageSize={10} />
    </div>
  );
}
