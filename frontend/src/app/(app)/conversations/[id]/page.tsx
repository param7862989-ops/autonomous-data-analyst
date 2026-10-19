"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import { QuestionComposer } from "@/components/analysis/question-composer";
import { RunCard } from "@/components/analysis/run-card";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { useAskQuestion, useConversation, useServerConfig, isActive } from "@/lib/analyses/api";
import { ApiError } from "@/lib/api/errors";
import { type ColumnProfile, useDataset } from "@/lib/datasets/api";

/** Starter questions built from the dataset's own columns. */
function starterQuestions(columns: ColumnProfile[]): string[] {
  const label = (c: ColumnProfile) => c.original_name;
  const date = columns.find((c) => c.semantic_type === "datetime");
  const measure = columns.find(
    (c) => c.semantic_type === "numeric" && !/id$/i.test(c.name) && c.unique_count > 10,
  );
  const category = columns.find(
    (c) => c.semantic_type === "categorical" && c.unique_count >= 2 && c.unique_count <= 30,
  );
  const questions: string[] = [];
  if (measure && category) questions.push(`Which ${label(category)} has the highest total ${label(measure)}?`);
  if (measure && date) questions.push(`How has ${label(measure)} changed over time?`);
  if (measure) questions.push(`Are there unusual values in ${label(measure)}?`);
  questions.push("Which columns have missing values, and how many?");
  return questions.slice(0, 4);
}

export default function ConversationPage() {
  const { id } = useParams<{ id: string }>();
  const conversation = useConversation(id);
  const config = useServerConfig();
  const dataset = useDataset(conversation.data?.dataset_id ?? "");
  const ask = useAskQuestion(id);
  const [question, setQuestion] = useState("");
  const composer = useRef<HTMLTextAreaElement>(null);
  const end = useRef<HTMLDivElement>(null);
  const runCount = conversation.data?.runs.length ?? 0;

  useEffect(() => {
    if (runCount) end.current?.scrollIntoView({ block: "end" });
  }, [runCount]);

  const starters = useMemo(
    () => (dataset.data ? starterQuestions(dataset.data.profile.columns) : []),
    [dataset.data],
  );

  if (conversation.isPending) {
    return (
      <p className="flex items-center gap-2 text-slate">
        <Spinner size={16} label="" /> Loading conversation…
      </p>
    );
  }
  if (conversation.isError) {
    const missing = conversation.error instanceof ApiError && conversation.error.status === 404;
    return (
      <div className="max-w-xl">
        <Alert
          tone={missing ? "info" : "danger"}
          title={missing ? "Conversation not found" : "The conversation couldn't be loaded"}
          action={
            missing ? null : (
              <Button variant="secondary" size="sm" onClick={() => conversation.refetch()}>
                Try again
              </Button>
            )
          }
        >
          {missing ? "It may have been deleted. " : `${conversation.error.message} `}
          <Link href="/datasets" className="font-medium text-primary underline underline-offset-2">
            Go to datasets
          </Link>
        </Alert>
      </div>
    );
  }

  const data = conversation.data;
  const running = data.runs.some((run) => isActive(run.status));
  const disabledReason = config.data && !config.data.analysis_enabled
    ? "Analysis is unavailable: this server has no language model configured. Uploading and profiling still work."
    : running
      ? "Wait for the current analysis to finish, or cancel it."
      : null;

  function submit(text = question) {
    const trimmed = text.trim();
    if (!trimmed) return;
    ask.mutate(trimmed, { onSuccess: () => setQuestion("") });
  }

  function followUp(text: string) {
    setQuestion(text);
    composer.current?.focus();
  }

  return (
    <div className="mx-auto max-w-4xl">
      <Link
        href={`/datasets/${data.dataset_id}`}
        className="inline-flex items-center gap-1.5 text-sm text-slate hover:text-ink"
      >
        <ArrowLeft size={14} aria-hidden="true" /> {data.dataset_name}
      </Link>
      <h1 className="mt-3 text-2xl font-semibold tracking-tight break-words">{data.title}</h1>

      <div className="mt-8 space-y-12">
        {data.runs.map((run) => (
          <RunCard key={run.id} runId={run.id} onFollowUp={followUp} />
        ))}
      </div>

      {data.runs.length === 0 ? (
        <section aria-labelledby="start-heading" className="mt-6">
          <h2 id="start-heading" className="font-medium">
            Ask your first question
          </h2>
          <p className="mt-1 text-sm text-slate">
            The analyst plans the analysis, runs computations on {data.dataset_name}, and shows
            the results behind its answer. Some questions this dataset can answer:
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            {starters.map((starter) => (
              <button
                key={starter}
                type="button"
                onClick={() => followUp(starter)}
                className="rounded-full border border-rule-strong bg-surface px-3 py-1 text-left text-sm hover:border-primary hover:text-primary"
              >
                {starter}
              </button>
            ))}
          </div>
        </section>
      ) : null}

      <div ref={end} className="sticky bottom-0 mt-10 bg-paper pt-3 pb-4">
        <QuestionComposer
          ref={composer}
          value={question}
          onChange={setQuestion}
          onSubmit={() => submit()}
          disabledReason={disabledReason}
          pending={ask.isPending}
          error={ask.isError ? ask.error.message : null}
        />
      </div>
    </div>
  );
}
