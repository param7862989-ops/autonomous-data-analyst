import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { jsonResponse, mockFetch, renderWithQuery } from "@/test/utils";

import { AuthForm } from "./auth-form";

const replace = vi.fn();
let search = "";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(search),
}));

const USER = {
  id: "0b8f7d1e-4b0a-4c43-9d5e-2a8c4b8b0c11",
  email: "ana@example.com",
  created_at: "2026-10-19T00:00:00Z",
};

function errorBody(code: string, message: string) {
  return { error: { code, message, details: null, request_id: "r1" } };
}

beforeEach(() => {
  replace.mockReset();
  search = "";
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("AuthForm (login)", () => {
  it("validates fields before calling the API", async () => {
    const fetchMock = mockFetch(() => jsonResponse(USER));
    renderWithQuery(<AuthForm mode="login" />);
    await userEvent.type(screen.getByLabelText("Email"), "not-an-email");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(screen.getByText(/enter an email address/i)).toBeInTheDocument();
    expect(screen.getByText(/enter your password/i)).toBeInTheDocument();
    expect(screen.getByLabelText("Email")).toHaveAttribute("aria-invalid", "true");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("signs in and follows a safe next path", async () => {
    search = "next=%2Fdatasets%2F42";
    const fetchMock = mockFetch(() => jsonResponse(USER));
    renderWithQuery(<AuthForm mode="login" />);
    await userEvent.type(screen.getByLabelText("Email"), " ana@example.com ");
    await userEvent.type(screen.getByLabelText("Password"), "correct horse battery");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/datasets/42"));
    const request = fetchMock.mock.calls[0][0] as Request;
    expect(new URL(request.url).pathname).toBe("/api/auth/login");
    expect(request.method).toBe("POST");
    expect(await request.json()).toEqual({
      email: "ana@example.com",
      password: "correct horse battery",
    });
  });

  it("ignores an off-site next parameter", async () => {
    search = "next=https%3A%2F%2Fevil.example";
    mockFetch(() => jsonResponse(USER));
    renderWithQuery(<AuthForm mode="login" />);
    await userEvent.type(screen.getByLabelText("Email"), "ana@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "correct horse battery");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/"));
  });

  it("shows the server message for wrong credentials", async () => {
    mockFetch(() =>
      jsonResponse(errorBody("invalid_credentials", "Incorrect email or password."), 401),
    );
    renderWithQuery(<AuthForm mode="login" />);
    await userEvent.type(screen.getByLabelText("Email"), "ana@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "wrong password");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Incorrect email or password.");
    expect(replace).not.toHaveBeenCalled();
  });
});

describe("AuthForm (register)", () => {
  it("enforces the minimum password length", async () => {
    const fetchMock = mockFetch(() => jsonResponse(USER, 201));
    renderWithQuery(<AuthForm mode="register" />);
    await userEvent.type(screen.getByLabelText("Email"), "ana@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "short");
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));
    expect(screen.getByText(/at least 10 characters/i)).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("explains when the email is already registered", async () => {
    mockFetch(() =>
      jsonResponse(errorBody("email_taken", "An account with this email already exists."), 409),
    );
    renderWithQuery(<AuthForm mode="register" />);
    await userEvent.type(screen.getByLabelText("Email"), "ana@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "correct horse battery");
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/already exists/);
  });
});
