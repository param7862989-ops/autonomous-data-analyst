import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { jsonResponse, mockFetch, renderWithQuery } from "@/test/utils";

import { StartConversationButton } from "./dataset-conversations";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

afterEach(() => vi.unstubAllGlobals());

describe("StartConversationButton", () => {
  it("starts a conversation about the selected dataset", async () => {
    const bodies: unknown[] = [];
    mockFetch(async (request) => {
      bodies.push(await request.json());
      return jsonResponse({ id: "c9", dataset_id: "d7", runs: [] }, 201);
    });
    renderWithQuery(<StartConversationButton datasetId="d7" />);
    await userEvent.click(screen.getByRole("button", { name: "Ask a question" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/conversations/c9"));
    expect(bodies).toEqual([{ dataset_id: "d7" }]);
  });
});
