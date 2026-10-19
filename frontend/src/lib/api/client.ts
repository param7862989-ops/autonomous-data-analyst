import createClient from "openapi-fetch";

import { networkError, toApiError } from "./errors";
import type { paths } from "./schema";

/**
 * Header required by the backend on state-changing requests. A cross-site HTML form cannot set
 * custom headers, and a cross-site fetch that sets one is blocked by the CORS preflight.
 */
export const CSRF_HEADER = { "X-Requested-With": "fetch" } as const;

function baseUrl(): string {
  // Same-origin: the Next.js server forwards /api/* to the backend.
  return typeof window === "undefined" ? "http://localhost" : window.location.origin;
}

export const api = createClient<paths>({
  baseUrl: baseUrl(),
  credentials: "same-origin",
  headers: CSRF_HEADER,
  // Resolve fetch at call time so tests can stub the global.
  fetch: (request: Request) => globalThis.fetch(request),
});

type FetchResult<T> = { data?: T; error?: unknown; response: Response };

/** Await an openapi-fetch call and return its data, or throw an {@link ApiError}. */
export async function unwrap<T>(call: Promise<FetchResult<T>>): Promise<T> {
  let result: FetchResult<T>;
  try {
    result = await call;
  } catch {
    throw networkError();
  }
  if (result.error !== undefined || !result.response.ok) {
    throw toApiError(result.response.status, result.error);
  }
  return result.data as T;
}
