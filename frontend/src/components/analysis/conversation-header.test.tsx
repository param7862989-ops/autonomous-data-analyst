import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { jsonResponse, mockFetch, renderWithQuery } from "@/test/utils";

import { ConversationHeader } from "./conversation-header";

const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));

afterEach(() => {
  vi.unstubAllGlobals();
  replace.mockReset();
});

const render = () =>
  renderWithQuery(<ConversationHeader id="c1" title="Old title" datasetId="d1" />);
const failure = () =>
  jsonResponse(
    { error: { code: "internal_error", message: "It failed.", details: null, request_id: "r" } },
    500,
  );

describe("ConversationHeader", () => {
  it("renames with a trimmed title", async () => {
    const sent: unknown[] = [];
    mockFetch(async (request) => {
      sent.push([request.method, new URL(request.url).pathname, await request.json()]);
      return jsonResponse({ id: "c1", title: "New title", runs: [] });
    });
    render();
    await userEvent.click(screen.getByRole("button", { name: "Rename" }));
    const field = screen.getByLabelText("Conversation title");
    await userEvent.clear(field);
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.type(field, "  New title  {Enter}");
    await waitFor(() =>
      expect(screen.queryByLabelText("Conversation title")).not.toBeInTheDocument(),
    );
    expect(sent).toEqual([["PATCH", "/api/conversations/c1", { title: "New title" }]]);
  });

  it("keeps the edit open when renaming fails", async () => {
    mockFetch(failure);
    render();
    await userEvent.click(screen.getByRole("button", { name: "Rename" }));
    await userEvent.type(screen.getByLabelText("Conversation title"), "!{Enter}");
    expect(await screen.findByText("It failed.")).toBeInTheDocument();
    expect(screen.getByLabelText("Conversation title")).toHaveValue("Old title!");
  });

  it("cancels an edit with Escape", async () => {
    const fetchMock = mockFetch(failure);
    render();
    await userEvent.click(screen.getByRole("button", { name: "Rename" }));
    await userEvent.type(screen.getByLabelText("Conversation title"), "x{Escape}");
    expect(screen.getByRole("heading", { name: "Old title" })).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("deletes only after confirmation, then returns to the dataset", async () => {
    const fetchMock = mockFetch(() => new Response(null, { status: 204 }));
    render();
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(fetchMock).not.toHaveBeenCalled();
    // jsdom has no showModal, so the dialog's content counts as hidden.
    await userEvent.click(screen.getByText("Delete conversation", { selector: "button" }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/datasets/d1"));
    const request = fetchMock.mock.calls[0][0] as Request;
    expect([request.method, new URL(request.url).pathname]).toEqual([
      "DELETE",
      "/api/conversations/c1",
    ]);
  });

  it("stays on the page when deleting fails", async () => {
    mockFetch(failure);
    render();
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    await userEvent.click(screen.getByText("Delete conversation", { selector: "button" }));
    expect(await screen.findByText("It failed.")).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
  });
});
