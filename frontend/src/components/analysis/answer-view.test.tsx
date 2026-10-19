import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { AgentOutcome } from "@/lib/analyses/api";

import { AnswerView } from "./answer-view";

function outcome(unverified: string[] = []): AgentOutcome {
  return {
    status: "completed",
    stop_reason: "completed",
    plan: null,
    answer: {
      summary: "Revenue fell 34.5% in Q3 2024.",
      findings: [
        { statement: "West dropped by $157,871.", kind: "fact", evidence: ["r1"] },
        { statement: "Weather may have played a role.", kind: "hypothesis", evidence: [] },
      ],
      caveats: ["Q3 means July to September 2024."],
      chart_ids: [],
      follow_up_questions: ["Which products drove it?"],
    },
    results: [],
    charts: [],
    grounding: {
      checked_numbers: 2,
      unverified_numbers: unverified,
      invalid_references: [],
      unsupported_facts: [],
    },
    error_code: null,
    error_message: null,
    iterations: 2,
    tool_calls: 1,
    usage: {},
  };
}

describe("AnswerView", () => {
  it("highlights verified figures and separates facts from hypotheses", () => {
    render(<AnswerView outcome={outcome()} onCite={vi.fn()} />);
    const marks = Array.from(document.querySelectorAll("mark")).map((m) => m.textContent);
    expect(marks).toEqual(["34.5%", "$157,871"]);
    expect(screen.getByText("What the data shows")).toBeInTheDocument();
    expect(screen.getByText("Hypothesis")).toBeInTheDocument();
    expect(screen.getByText("Weather may have played a role.")).toBeInTheDocument();
    expect(screen.queryByText(/could not be matched/)).not.toBeInTheDocument();
  });

  it("flags figures that failed the grounding check", () => {
    render(<AnswerView outcome={outcome(["34.5%"])} onCite={vi.fn()} />);
    expect(screen.getByTitle(/could not be matched/)).toHaveTextContent("34.5%");
    expect(screen.getByText(/1 statement\(s\) or figure\(s\)/)).toBeInTheDocument();
    const marks = Array.from(document.querySelectorAll("mark")).map((m) => m.textContent);
    expect(marks).toEqual(["$157,871"]);
  });

  it("links evidence and suggests follow-ups", async () => {
    const onCite = vi.fn();
    const onFollowUp = vi.fn();
    render(<AnswerView outcome={outcome()} onCite={onCite} onFollowUp={onFollowUp} />);
    await userEvent.click(screen.getByRole("button", { name: "Show the computed result r1" }));
    expect(onCite).toHaveBeenCalledWith("r1");
    await userEvent.click(screen.getByRole("button", { name: "Which products drove it?" }));
    expect(onFollowUp).toHaveBeenCalledWith("Which products drove it?");
  });
});
