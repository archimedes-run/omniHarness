"use client";

import {
  QueryClient,
  QueryClientProvider as TanStackQueryClientProvider,
} from "@tanstack/react-query";

/**
 * Defaults measured against, not guessed (Phase 2.5).
 *
 * - No retry for an HTTP error. A 4xx will not change on retry, and the library
 *   default (three retries, 1 s + 2 s + 4 s backoff) is what kept the Agents
 *   page loading for seconds on a 403 before it showed anything. A network
 *   failure (fetch throws TypeError) is retried once.
 * - 10 s staleness, so the sidebar badges and the page they sit on share one
 *   request instead of each refetching on mount. Polling hooks keep their own
 *   intervals, and mutations invalidate what they change.
 */
export function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 10_000,
        retry: (failureCount, error) =>
          failureCount < 1 && error instanceof TypeError,
      },
    },
  });
}

const queryClient = makeQueryClient();

export function QueryClientProvider({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <TanStackQueryClientProvider client={queryClient}>
      {children}
    </TanStackQueryClientProvider>
  );
}
