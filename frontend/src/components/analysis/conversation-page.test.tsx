import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import ConversationPage from "@/app/(app)/conversations/[id]/page";
import { jsonResponse, mockFetch } from "@/test/utils";

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "c1" }),
  useRouter: () => ({ replace: vi.fn() }),
}));

afterEach(() => vi.unstubAllGlobals());

const RUN = {
  id: "run-1",
  conversation_id: "c1",
  dataset_id: "d1",
  question: "Why did revenue fall?",
  status: "failed",
  stop_reason: "error",
  answer_summary: null,
  created_at: "2026-11-22T10:00:00Z",
  finished_at: "2026-11-22T10:01:00Z",
};
const COLUMNS = [
  { name: "region", original_name: "Region", semantic_type: "categorical", unique_count: 4 },
  { name: "revenue", original_name: "Revenue", semantic_type: "numeric", unique_count: 900 },
];

function setup({ runs = [] as object[], analysis = true } = {}) {
  const state = { down: false, deleted: false, asked: [] as unknown[] };
  mockFetch(async (request) => {
    if (state.down) return new Response("down", { status: 503 });
    const { pathname } = new URL(request.url);
    if (request.method === "POST") {
      state.asked.push(await request.json());
      return jsonResponse({ ...RUN, id: "run-2", status: "queued" }, 202);
    }
    if (pathname === "/api/config") {
      return jsonResponse({ analysis_enabled: analysis, model: "m", max_question_length: 2000 });
    }
    if (pathname === "/api/datasets/d1") return jsonResponse({ profile: { columns: COLUMNS } });
    if (pathname === "/api/conversations/c1") {
      if (state.deleted) {
        return jsonResponse(
          { error: { code: "not_found", message: "Gone", details: null, request_id: "r" } },
          404,
        );
      }
      return jsonResponse({ id: "c1", dataset_id: "d1", dataset_name: "Sales", title: "Review", runs });
    }
    return jsonResponse({ ...RUN, events: [], outcome: null, error_message: "It timed out." });
  });
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <ConversationPage />
    </QueryClientProvider>,
  );
  const refetch = () =>
    act(async () => {
      await client.refetchQueries({ queryKey: ["conversations"] });
      // TanStack Query notifies components on the next timer tick; without this the assertions
      // would see the page as it was before the refetch finished.
      await new Promise((resolve) => setTimeout(resolve, 20));
    });
  return { state, refetch };
}

describe("Conversation page", () => {
  it("offers starter questions from the dataset's columns and submits one", async () => {
    const { state } = setup();
    const question = "Which Region has the highest total Revenue?";
    await userEvent.click(await screen.findByRole("button", { name: question }));
    expect(screen.getByRole("textbox")).toHaveValue(question);
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    await waitFor(() => expect(state.asked).toEqual([{ question }]));
  });

  it("retries a failed question without losing what was typed", async () => {
    const { state } = setup({ runs: [RUN] });
    const retry = await screen.findByRole("button", { name: `Retry: ${RUN.question}` });
    await userEvent.type(screen.getByRole("textbox"), "My next question");
    await userEvent.click(retry);
    await waitFor(() => expect(state.asked).toEqual([{ question: RUN.question }]));
    expect(screen.getByRole("textbox")).toHaveValue("My next question");
  });

  it("offers no retry when analysis is unavailable", async () => {
    setup({ runs: [RUN], analysis: false });
    expect(await screen.findByText("It timed out.")).toBeInTheDocument();
    await screen.findByText(/no language model configured/);
    expect(screen.queryByRole("button", { name: /Retry/ })).toBeNull();
  });

  it("keeps the page and the typed question when a background refresh fails", async () => {
    const { state, refetch } = setup();
    await userEvent.type(await screen.findByRole("textbox"), "Half-typed");
    state.down = true;
    await refetch();
    expect(screen.getByRole("heading", { name: "Review" })).toBeInTheDocument();
    expect(screen.getByRole("textbox")).toHaveValue("Half-typed");
  });

  it("shows not found when the conversation was deleted elsewhere", async () => {
    const { state, refetch } = setup();
    await screen.findByRole("heading", { name: "Review" });
    state.deleted = true;
    await refetch();
    expect(await screen.findByText("Conversation not found")).toBeInTheDocument();
  });
});
