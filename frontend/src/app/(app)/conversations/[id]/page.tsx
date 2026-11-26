"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import { ConversationHeader } from "@/components/analysis/conversation-header";
import { SuggestionList } from "@/components/analysis/answer-view";
import { QuestionComposer } from "@/components/analysis/question-composer";
import { RunCard } from "@/components/analysis/run-card";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { useAskQuestion, useConversation, useServerConfig, isActive } from "@/lib/analyses/api";
import { isNotFound } from "@/lib/api/errors";
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
  const runCount = conversation.data?.runs.length;
  const seenRuns = useRef<number | undefined>(undefined);

  useEffect(() => {
    if (runCount === undefined) return;
    // Follow a newly asked question, but leave the position alone when the page opens, so a
    // link from history can land on its own question.
    if (seenRuns.current !== undefined && runCount > seenRuns.current) {
      end.current?.scrollIntoView({ block: "end" });
    }
    seenRuns.current = runCount;
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
  const missing = isNotFound(conversation.error);
  if (!conversation.data || missing) {
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
          {missing ? "It may have been deleted. " : `${conversation.error?.message ?? ""} `}
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
    <div>
      <header className="border-b border-ink pb-6">
        <div className="mb-4 text-sm">
          <Link
            href={`/datasets/${data.dataset_id}`}
            className="text-slate underline-offset-4 hover:text-ink hover:underline"
          >
            Dataset: {data.dataset_name}
          </Link>
        </div>
        <ConversationHeader id={id} title={data.title} datasetId={data.dataset_id} />
      </header>

      <div>
        {data.runs.map((run, index) => (
          <RunCard
            key={run.id}
            runId={run.id}
            number={index + 1}
            onFollowUp={followUp}
            onRetry={disabledReason || ask.isPending ? undefined : (text) => ask.mutate(text)}
          />
        ))}
      </div>

      {data.runs.length === 0 ? (
        <section
          aria-labelledby="start-heading"
          className="grid gap-x-10 gap-y-3 py-8 lg:grid-cols-[12rem_minmax(0,1fr)]"
        >
          <h2 id="start-heading" className="text-[1.1875rem] leading-snug">
            Ask your first question
          </h2>
          <div>
            <p className="max-w-[62ch] text-slate">
              Answers come from computations on {data.dataset_name}, and each figure is checked
              against them. Questions this dataset can answer:
            </p>
            <SuggestionList questions={starters} onPick={followUp} />
          </div>
        </section>
      ) : null}

      <div className="sticky bottom-0 bg-paper pt-4 pb-4 lg:ml-[calc(12rem+2.5rem)]">
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
      <div ref={end} />
    </div>
  );
}
