import type { components } from "./schema";

type ErrorEnvelope = components["schemas"]["ErrorResponse"];

/** A failed API call, normalised from the backend's error envelope or a transport failure. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: unknown;
  readonly requestId: string | null;

  constructor(options: {
    status: number;
    code: string;
    message: string;
    details?: unknown;
    requestId?: string | null;
  }) {
    super(options.message);
    this.name = "ApiError";
    this.status = options.status;
    this.code = options.code;
    this.details = options.details ?? null;
    this.requestId = options.requestId ?? null;
  }

  get isNetworkError(): boolean {
    return this.status === 0;
  }
}

function isErrorEnvelope(body: unknown): body is ErrorEnvelope {
  if (typeof body !== "object" || body === null || !("error" in body)) return false;
  const inner = (body as { error: unknown }).error;
  return (
    typeof inner === "object" &&
    inner !== null &&
    typeof (inner as { code?: unknown }).code === "string" &&
    typeof (inner as { message?: unknown }).message === "string"
  );
}

function fallbackMessage(status: number): string {
  if (status === 401) return "Your session has ended. Sign in again.";
  if (status === 403) return "You don't have access to this.";
  if (status === 404) return "This item doesn't exist or was deleted.";
  if (status === 413) return "The request is too large.";
  if (status === 429) return "Too many requests. Wait a moment and try again.";
  if (status >= 500) return "The server couldn't complete the request. Try again shortly.";
  return "The request couldn't be completed.";
}

export function toApiError(status: number, body: unknown): ApiError {
  if (isErrorEnvelope(body)) {
    return new ApiError({
      status,
      code: body.error.code,
      message: body.error.message,
      details: body.error.details,
      requestId: body.error.request_id ?? null,
    });
  }
  return new ApiError({ status, code: "http_error", message: fallbackMessage(status) });
}

export const networkError = () =>
  new ApiError({
    status: 0,
    code: "network_error",
    message: "Can't reach the server. Check your connection and try again.",
  });
