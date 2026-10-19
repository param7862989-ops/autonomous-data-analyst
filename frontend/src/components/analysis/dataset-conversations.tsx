"use client";

import { MessageSquarePlus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { useConversations, useCreateConversation, useServerConfig } from "@/lib/analyses/api";
import { formatDateTime } from "@/lib/format";

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
  const conversations = useConversations(datasetId);
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
      {conversations.isPending ? (
        <p className="mt-2 text-sm text-slate">Loading…</p>
      ) : conversations.isError ? (
        <p className="mt-2 text-sm text-danger">{conversations.error.message}</p>
      ) : conversations.data.items.length === 0 ? (
        <p className="mt-2 text-sm text-slate">
          No questions asked yet. Start a conversation to analyse this dataset.
        </p>
      ) : (
        <ul className="mt-3 divide-y divide-rule rounded-(--radius-panel) border border-rule bg-surface">
          {conversations.data.items.map((item) => (
            <li key={item.id} className="flex flex-wrap items-baseline justify-between gap-2 px-4 py-2.5 text-sm">
              <Link
                href={`/conversations/${item.id}`}
                className="min-w-0 font-medium text-primary underline-offset-2 hover:underline"
              >
                {item.title}
              </Link>
              <span className="text-slate">
                {item.run_count} question{item.run_count === 1 ? "" : "s"},{" "}
                {formatDateTime(item.updated_at)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
