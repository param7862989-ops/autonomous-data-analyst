"use client";

import Link from "next/link";
import { useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Pager } from "@/components/ui/pager";
import { Spinner } from "@/components/ui/spinner";
import { useConversations } from "@/lib/analyses/api";
import { formatDateTime } from "@/lib/format";

/** The user's conversations, newest activity first: all of them, or one dataset's. */
export function ConversationList({
  datasetId,
  pageSize = 25,
}: {
  datasetId?: string;
  pageSize?: number;
}) {
  const [offset, setOffset] = useState(0);
  const conversations = useConversations(datasetId, pageSize, offset);

  if (conversations.isPending) {
    return (
      <p className="flex items-center gap-2 text-sm text-slate">
        <Spinner size={14} label="" /> Loading conversations…
      </p>
    );
  }
  if (!conversations.data) {
    return (
      <Alert
        tone="danger"
        title="Conversations couldn't be loaded"
        action={
          <Button variant="secondary" size="sm" onClick={() => conversations.refetch()}>
            Try again
          </Button>
        }
      >
        {conversations.error?.message}
      </Alert>
    );
  }

  const { items, total } = conversations.data;
  if (!items.length && offset === 0) {
    return (
      <p className="text-sm text-slate">
        {datasetId
          ? "No questions asked yet. Start a conversation to analyse this dataset."
          : "No conversations yet. Open a dataset and ask a question to start one."}
      </p>
    );
  }
  return (
    <>
      <ul className="divide-y divide-rule border-y border-rule">
        {items.map((item) => (
          <li
            key={item.id}
            className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 py-3 text-sm"
          >
            <div className="min-w-0">
              <Link
                href={`/conversations/${item.id}`}
                className="font-serif text-[17px] font-semibold break-words text-ink underline decoration-rule-strong underline-offset-4 hover:decoration-ink"
              >
                {item.title}
              </Link>
              {datasetId ? null : (
                <span className="block break-words text-slate">{item.dataset_name}</span>
              )}
            </div>
            <span className="text-slate">
              {item.run_count} question{item.run_count === 1 ? "" : "s"},{" "}
              {formatDateTime(item.updated_at)}
            </span>
          </li>
        ))}
      </ul>
      <Pager
        label="Conversation pages"
        offset={offset}
        count={items.length}
        pageSize={pageSize}
        total={total}
        busy={conversations.isPlaceholderData}
        onChange={setOffset}
      />
    </>
  );
}
