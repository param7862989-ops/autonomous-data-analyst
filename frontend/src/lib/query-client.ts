import { QueryClient } from "@tanstack/react-query";

import { ApiError } from "@/lib/api/errors";

/** Retry only failures that a retry can fix: network errors and 5xx responses. */
export function shouldRetry(failureCount: number, error: unknown): boolean {
  if (failureCount >= 2) return false;
  if (error instanceof ApiError) return error.isNetworkError || error.status >= 500;
  return false;
}

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: shouldRetry,
        staleTime: 30_000,
        refetchOnWindowFocus: false,
      },
      mutations: {
        retry: false,
      },
    },
  });
}
