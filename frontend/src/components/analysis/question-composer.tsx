"use client";

import { ArrowUp } from "lucide-react";
import { forwardRef, useId } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

export const MAX_QUESTION_LENGTH = 2000;

export const QuestionComposer = forwardRef<
  HTMLTextAreaElement,
  {
    value: string;
    onChange: (value: string) => void;
    onSubmit: () => void;
    disabledReason: string | null;
    pending: boolean;
    error: string | null;
  }
>(function QuestionComposer({ value, onChange, onSubmit, disabledReason, pending, error }, ref) {
  const id = useId();
  const trimmed = value.trim();
  const tooLong = value.length > MAX_QUESTION_LENGTH;
  const blocked = Boolean(disabledReason) || pending;

  function submit(event?: React.FormEvent) {
    event?.preventDefault();
    if (!trimmed || tooLong || blocked) return;
    onSubmit();
  }

  return (
    <form onSubmit={submit} className="space-y-2">
      {error ? <Alert tone="danger">{error}</Alert> : null}
      <label htmlFor={id} className="sr-only">
        Ask a question about this dataset
      </label>
      <div className="flex items-end gap-2 rounded-(--radius-panel) border border-rule-strong bg-surface p-2 focus-within:border-primary">
        <textarea
          ref={ref}
          id={id}
          rows={2}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              submit();
            }
          }}
          placeholder="Ask about this dataset, e.g. Which region grew fastest last year?"
          className="max-h-48 min-h-11 flex-1 resize-y bg-transparent px-2 py-1.5 text-[15px] outline-none placeholder:text-slate/70"
          aria-describedby={`${id}-hint`}
          disabled={Boolean(disabledReason)}
        />
        <Button type="submit" disabled={!trimmed || tooLong || blocked} pending={pending} aria-label="Ask">
          {pending ? null : <ArrowUp size={16} aria-hidden="true" />}
          <span className="hidden sm:inline">Ask</span>
        </Button>
      </div>
      <p id={`${id}-hint`} className="text-sm text-slate">
        {disabledReason ??
          (tooLong
            ? `Shorten the question to ${MAX_QUESTION_LENGTH} characters (now ${value.length}).`
            : "Enter to ask, Shift+Enter for a new line. Follow-up questions use this conversation as context.")}
      </p>
    </form>
  );
});
