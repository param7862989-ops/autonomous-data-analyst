"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { TextField } from "@/components/ui/text-field";
import { useDeleteConversation, useRenameConversation } from "@/lib/analyses/api";

// Same limit as the API's ConversationUpdate.
const MAX_TITLE_LENGTH = 200;

/** The conversation's title, with rename and delete. */
export function ConversationHeader({
  id,
  title,
  datasetId,
}: {
  id: string;
  title: string;
  datasetId: string;
}) {
  const router = useRouter();
  const rename = useRenameConversation(id);
  const remove = useDeleteConversation();
  const [draft, setDraft] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);

  function stopEditing() {
    setDraft(null);
    rename.reset();
  }

  function save(event: React.FormEvent) {
    event.preventDefault();
    const next = draft?.trim();
    if (!next || rename.isPending) return;
    if (next === title) stopEditing();
    else rename.mutate(next, { onSuccess: stopEditing });
  }

  if (draft !== null) {
    return (
      <form
        onSubmit={save}
        onKeyDown={(event) => {
          if (event.key === "Escape" && !rename.isPending) stopEditing();
        }}
        className="mt-3 flex flex-wrap items-start gap-2"
      >
        <TextField
          label="Conversation title"
          value={draft}
          maxLength={MAX_TITLE_LENGTH}
          onChange={(event) => setDraft(event.target.value)}
          error={rename.error?.message}
          className="min-w-0 flex-1 basis-64"
          autoFocus
        />
        <div className="flex gap-2 sm:mt-[26px]">
          <Button type="submit" disabled={!draft.trim()} pending={rename.isPending}>
            Save
          </Button>
          <Button variant="secondary" onClick={stopEditing} type="button" disabled={rename.isPending}>
            Cancel
          </Button>
        </div>
      </form>
    );
  }

  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <h1 className="min-w-0 max-w-[46rem] text-[2rem] leading-[1.15] break-words sm:text-[2.375rem]">
        {title}
      </h1>
      <div className="flex gap-2">
        <Button variant="secondary" size="sm" onClick={() => setDraft(title)}>
          Rename
        </Button>
        <Button variant="secondary" size="sm" onClick={() => setConfirming(true)}>
          Delete
        </Button>
      </div>
      <ConfirmDialog
        open={confirming}
        title="Delete this conversation?"
        confirmLabel="Delete conversation"
        pending={remove.isPending}
        onCancel={() => {
          setConfirming(false);
          remove.reset();
        }}
        onConfirm={() =>
          remove.mutate(id, { onSuccess: () => router.replace(`/datasets/${datasetId}`) })
        }
      >
        <p>
          Its questions, answers and charts will be permanently removed. The dataset stays. This
          can&apos;t be undone.
        </p>
        {remove.isError ? (
          <p role="alert" className="mt-2 text-danger">
            {remove.error.message}
          </p>
        ) : null}
      </ConfirmDialog>
    </div>
  );
}
