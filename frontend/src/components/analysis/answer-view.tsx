import { AlertTriangle } from "lucide-react";

import type { AgentOutcome, Finding } from "@/lib/analyses/api";
import { namesWithDigits, splitFigures } from "@/lib/analyses/figures";

/**
 * Figures the backend matched to a computed result get the highlighter and a tick, as an
 * auditor ticks a figure agreed to its source; figures it could not match are flagged. Hypotheses get a dashed underline and a label, so
 * the distinction never depends on colour alone.
 */
function Statement({
  text,
  unverified,
  names,
}: {
  text: string;
  unverified: string[];
  names: string[];
}) {
  return (
    <>
      {splitFigures(text, unverified, names).map((segment, index) =>
        segment.figure === "verified" ? (
          <mark
            key={index}
            title="Matches a computed result"
            className="ticked tabular bg-highlight/70 px-0.5 text-ink"
          >
            {segment.text}
          </mark>
        ) : segment.figure === "unverified" ? (
          <span
            key={index}
            className="tabular border-b-2 border-dotted border-danger text-danger"
            title="This figure could not be matched to a computed result"
          >
            {segment.text}
          </span>
        ) : (
          <span key={index}>{segment.text}</span>
        ),
      )}
    </>
  );
}

function EvidenceLinks({
  finding,
  onCite,
}: {
  finding: Finding;
  onCite: (resultId: string) => void;
}) {
  if (!finding.evidence.length) return null;
  return (
    <span className="ml-1.5 inline-flex gap-1 align-middle">
      {finding.evidence.map((id) => (
        <button
          key={id}
          type="button"
          onClick={() => onCite(id)}
          className="tabular text-[13px] font-medium text-primary underline decoration-dotted underline-offset-2 hover:decoration-solid"
          aria-label={`Show the computed result ${id}`}
        >
          {id}
        </button>
      ))}
    </span>
  );
}

export function AnswerView({
  outcome,
  onCite,
  onFollowUp,
}: {
  outcome: AgentOutcome;
  onCite: (resultId: string) => void;
  onFollowUp?: (question: string) => void;
}) {
  const answer = outcome.answer;
  if (!answer) return null;
  const unverified = outcome.grounding?.unverified_numbers ?? [];
  const facts = answer.findings.filter((f) => f.kind === "fact");
  const hypotheses = answer.findings.filter((f) => f.kind === "hypothesis");
  const grounding = outcome.grounding;
  const names = namesWithDigits(outcome.results);
  const groundingIssues = grounding
    ? grounding.unverified_numbers.length +
      grounding.invalid_references.length +
      grounding.unsupported_facts.length
    : 0;

  return (
    <div className="space-y-5">
      <p className="max-w-[66ch] font-serif text-[19px] leading-[1.6]">
        <Statement text={answer.summary} unverified={unverified} names={names} />
      </p>

      {groundingIssues ? (
        <p className="flex gap-2 text-sm text-warning">
          <AlertTriangle size={16} aria-hidden="true" className="mt-0.5 shrink-0" />
          {groundingIssues} statement(s) or figure(s) in this answer don&apos;t match any computed
          result. They are underlined in red: check them before relying on them.
        </p>
      ) : null}

      {facts.length ? (
        <section aria-label="What the data shows">
          <h4 className="text-sm font-semibold">What the data shows</h4>
          <ul className="mt-2 max-w-[72ch] space-y-2">
            {facts.map((finding, index) => (
              <li key={index} className="border-l-2 border-ink pl-3">
                <Statement text={finding.statement} unverified={unverified} names={names} />
                <EvidenceLinks finding={finding} onCite={onCite} />
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {hypotheses.length ? (
        <section aria-label="Possible explanations">
          <h4 className="text-sm font-semibold">Possible explanations, not proven by the data</h4>
          <ul className="mt-2 max-w-[72ch] space-y-2">
            {hypotheses.map((finding, index) => (
              <li key={index} className="border-l-2 border-dashed border-rule-strong pl-3">
                <span className="mr-1.5 text-xs font-medium text-slate">Hypothesis</span>
                <span className="underline decoration-rule-strong decoration-dashed underline-offset-4">
                  {finding.statement}
                </span>
                <EvidenceLinks finding={finding} onCite={onCite} />
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {answer.caveats.length ? (
        <section aria-label="Caveats">
          <h4 className="text-sm font-semibold">Caveats</h4>
          <ul className="mt-1.5 list-disc space-y-1 pl-5 text-sm text-slate">
            {answer.caveats.map((caveat, index) => (
              <li key={index}>{caveat}</li>
            ))}
          </ul>
        </section>
      ) : null}

      {onFollowUp && answer.follow_up_questions.length ? (
        <section aria-label="Suggested follow-up questions">
          <h4 className="text-sm font-semibold">Ask next</h4>
          <SuggestionList questions={answer.follow_up_questions} onPick={onFollowUp} />
        </section>
      ) : null}
    </div>
  );
}

/** Questions to ask next, as a plain list: picking one puts it in the question box. */
export function SuggestionList({
  questions,
  onPick,
}: {
  questions: string[];
  onPick: (question: string) => void;
}) {
  return (
    <ul className="mt-1.5 space-y-1">
      {questions.map((question) => (
        <li key={question}>
          <button
            type="button"
            onClick={() => onPick(question)}
            className="text-left text-primary underline decoration-primary/40 underline-offset-4 hover:decoration-primary"
          >
            {question}
          </button>
        </li>
      ))}
    </ul>
  );
}
