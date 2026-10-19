import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { jsonResponse, mockFetch, renderWithQuery } from "@/test/utils";

type Upload = { url: string; headers: Headers; form: FormData };

/**
 * Stub fetch for the upload panel: GETs (generated client) arrive as Request objects; the
 * multipart upload arrives as (URL, init) with a jsdom FormData body, inspected directly because
 * Node's Request cannot serialise jsdom's FormData.
 */
function mockUploads(respond: (upload: Upload) => Response) {
  const uploads: Upload[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (input instanceof Request) return jsonResponse(LIMITS);
      const upload = {
        url: String(input),
        headers: new Headers(init?.headers),
        form: init?.body as FormData,
      };
      uploads.push(upload);
      return respond(upload);
    }),
  );
  return uploads;
}

import { UploadPanel, validateFile } from "./upload-panel";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, replace: vi.fn() }) }));

const LIMITS = {
  max_upload_bytes: 1024,
  max_rows: 500000,
  max_columns: 200,
  accepted_extensions: [".csv", ".tsv", ".txt", ".xlsx"],
};

function file(name: string, content = "a,b\n1,2\n") {
  return new File([content], name, { type: "text/csv" });
}

function errorBody(code: string, message: string, details: unknown = null) {
  return { error: { code, message, details, request_id: "r" } };
}

beforeEach(() => push.mockReset());
afterEach(() => vi.unstubAllGlobals());

describe("validateFile", () => {
  it("accepts supported files within the limit", () => {
    expect(validateFile(file("data.csv"), LIMITS.accepted_extensions, 1024)).toBeNull();
    expect(validateFile(file("Book.XLSX"), LIMITS.accepted_extensions, 1024)).toBeNull();
  });

  it("rejects other extensions, empty files and oversized files", () => {
    expect(validateFile(file("photo.png"))).toMatch(/\.csv or \.xlsx/);
    expect(validateFile(file("legacy.xls"))).toMatch(/\.csv or \.xlsx/);
    expect(validateFile(file("empty.csv", ""))).toMatch(/empty/);
    expect(validateFile(file("big.csv", "x".repeat(2048)), [".csv"], 1024)).toMatch(/limit/);
  });
});

describe("UploadPanel", () => {
  it("uploads a CSV and opens the new dataset", async () => {
    const uploads = mockUploads(() => jsonResponse({ id: "d1" }, 201));
    renderWithQuery(<UploadPanel />);
    await userEvent.upload(screen.getByLabelText(/choose a file/i), file("sales.csv"));
    await userEvent.type(screen.getByLabelText("Name (optional)"), "Q3 sales");
    await userEvent.click(screen.getByRole("button", { name: "Upload" }));

    await waitFor(() => expect(push).toHaveBeenCalledWith("/datasets/d1"));
    expect(uploads).toHaveLength(1);
    expect(new URL(uploads[0].url).pathname).toBe("/api/datasets");
    expect(uploads[0].headers.get("X-Requested-With")).toBe("fetch");
    expect((uploads[0].form.get("file") as File).name).toBe("sales.csv");
    expect(uploads[0].form.get("name")).toBe("Q3 sales");
    expect(uploads[0].form.get("sheet_name")).toBeNull();
  });

  it("blocks unsupported files before uploading", async () => {
    const fetchMock = mockFetch(() => jsonResponse(LIMITS));
    renderWithQuery(<UploadPanel />);
    await userEvent.upload(screen.getByLabelText(/choose a file/i), file("notes.pdf"), {
      applyAccept: false,
    });
    expect(screen.getByText(/choose a \.csv or \.xlsx file/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Upload" })).toBeDisabled();
    expect(fetchMock.mock.calls.every((call) => (call[0] as Request).method === "GET")).toBe(true);
  });

  it("asks for a sheet when the workbook has several, then retries with it", async () => {
    const uploads = mockUploads(({ form }) =>
      form.get("sheet_name")
        ? jsonResponse({ id: "d2" }, 201)
        : jsonResponse(
            errorBody("sheet_required", "Choose the sheet", { sheets: ["2023", "2024"] }),
            422,
          ),
    );
    renderWithQuery(<UploadPanel />);
    await userEvent.upload(screen.getByLabelText(/choose a file/i), file("book.xlsx", "PK"));
    await userEvent.click(screen.getByRole("button", { name: "Upload" }));

    expect(await screen.findByText(/several sheets/i)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("2024"));
    await userEvent.click(screen.getByRole("button", { name: "Import sheet" }));

    await waitFor(() => expect(push).toHaveBeenCalledWith("/datasets/d2"));
    expect(uploads[1].form.get("sheet_name")).toBe("2024");
  });

  it("shows the server's explanation when a file is rejected", async () => {
    mockUploads(() =>
      jsonResponse(errorBody("malformed_file", "Line 3 has 3 values but the first row has 2."), 422),
    );
    renderWithQuery(<UploadPanel />);
    await userEvent.upload(screen.getByLabelText(/choose a file/i), file("bad.csv"));
    await userEvent.click(screen.getByRole("button", { name: "Upload" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Line 3 has 3 values");
    expect(push).not.toHaveBeenCalled();
  });
});
