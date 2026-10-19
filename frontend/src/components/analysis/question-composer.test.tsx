import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { QuestionComposer } from "./question-composer";

function Harness({ onSubmit, disabledReason = null }: { onSubmit: () => void; disabledReason?: string | null }) {
  const [value, setValue] = useState("");
  return (
    <QuestionComposer
      value={value}
      onChange={setValue}
      onSubmit={onSubmit}
      disabledReason={disabledReason}
      pending={false}
      error={null}
    />
  );
}

describe("QuestionComposer", () => {
  it("submits on Enter and adds a line on Shift+Enter", async () => {
    const onSubmit = vi.fn();
    render(<Harness onSubmit={onSubmit} />);
    const box = screen.getByLabelText("Ask a question about this dataset");
    await userEvent.type(box, "Why{Shift>}{Enter}{/Shift}now");
    expect(box).toHaveValue("Why\nnow");
    expect(onSubmit).not.toHaveBeenCalled();
    await userEvent.type(box, "{Enter}");
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it("does not submit blank questions", async () => {
    const onSubmit = vi.fn();
    render(<Harness onSubmit={onSubmit} />);
    await userEvent.type(screen.getByLabelText("Ask a question about this dataset"), "   {Enter}");
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Ask" })).toBeDisabled();
  });

  it("explains why asking is unavailable", () => {
    render(<Harness onSubmit={vi.fn()} disabledReason="Analysis is unavailable." />);
    expect(screen.getByText("Analysis is unavailable.")).toBeInTheDocument();
    expect(screen.getByLabelText("Ask a question about this dataset")).toBeDisabled();
  });
});
