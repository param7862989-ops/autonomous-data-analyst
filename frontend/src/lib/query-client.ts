import { MutationCache, QueryCache, QueryClient } from "@tanstack/react-query";

import { ApiError } from "@/lib/api/errors";

/** Retry only failures that a retry can fix: network errors and 5xx responses. */
export function shouldRetry(failureCount: number, error: unknown): boolean {
  if (failureCount >= 2) return false;
  if (error instanceof ApiError) return error.isNetworkError || error.status >= 500;
  return false;
}

const isUnauthenticated = (error: unknown) => error instanceof ApiError && error.status === 401;

export function createQueryClient(): QueryClient {
  // When any request reports 401 (the session expired mid-use), re-check the session. The
  // auth guard then sends the user to sign in.
  const onError = (error: unknown) => {
    if (isUnauthenticated(error)) {
      void client.invalidateQueries({ queryKey: ["auth", "me"] });
    }
  };
  const client: QueryClient = new QueryClient({
    queryCache: new QueryCache({
      onError: (error, query) => {
        if (query.queryKey[0] !== "auth") onError(error);
      },
    }),
    mutationCache: new MutationCache({ onError }),
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
  return client;
}
