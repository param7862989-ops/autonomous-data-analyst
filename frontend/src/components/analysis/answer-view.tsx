import { clsx } from "clsx";
import { AlertTriangle } from "lucide-react";

import type { AgentOutcome, Finding } from "@/lib/analyses/api";
import { splitFigures } from "@/lib/analyses/figures";

/**
 * Figures in facts that the backend verified against computed results get the highlighter;
 * figures it could not verify are flagged. Hypotheses get a dashed underline and a label, so
 * the distinction never depends on colour alone.
 */
function Statement({ text, unverified }: { text: string; unverified: string[] }) {
  return (
    <>
      {splitFigures(text, unverified).map((segment, index) =>
        segment.figure === "verified" ? (
          <mark key={index} className="tabular rounded-[2px] bg-highlight/70 px-0.5 text-ink">
            {segment.text}
          </mark>
        ) : segment.figure === "unverified" ? (
          <span
            key={index}
            className="tabular border-b-2 border-dotted border-danger"
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
          className="rounded-[3px] border border-rule-strong px-1 text-xs text-slate hover:border-primary hover:text-primary"
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
  const groundingIssues = grounding
    ? grounding.unverified_numbers.length +
      grounding.invalid_references.length +
      grounding.unsupported_facts.length
    : 0;

  return (
    <div className="space-y-5">
      <p className="font-serif text-[17px] leading-relaxed">
        <Statement text={answer.summary} unverified={unverified} />
      </p>

      {groundingIssues ? (
        <p className="flex gap-2 text-sm text-warning">
          <AlertTriangle size={16} aria-hidden="true" className="mt-0.5 shrink-0" />
          {groundingIssues} statement(s) or figure(s) in this answer could not be matched to a
          computed result. They are marked; treat them with care.
        </p>
      ) : null}

      {facts.length ? (
        <section aria-label="What the data shows">
          <h4 className="text-sm font-semibold">What the data shows</h4>
          <ul className="mt-2 space-y-2">
            {facts.map((finding, index) => (
              <li key={index} className="border-l-2 border-ink pl-3">
                <Statement text={finding.statement} unverified={unverified} />
                <EvidenceLinks finding={finding} onCite={onCite} />
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {hypotheses.length ? (
        <section aria-label="Possible explanations">
          <h4 className="text-sm font-semibold">Possible explanations, not proven by the data</h4>
          <ul className="mt-2 space-y-2">
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
        <div className="flex flex-wrap gap-2" aria-label="Suggested follow-up questions">
          {answer.follow_up_questions.map((question) => (
            <button
              key={question}
              type="button"
              onClick={() => onFollowUp(question)}
              className={clsx(
                "rounded-full border border-rule-strong bg-surface px-3 py-1 text-left text-sm",
                "hover:border-primary hover:text-primary",
              )}
            >
              {question}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
