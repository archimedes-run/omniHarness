import { useQuery } from "@tanstack/react-query";

import { loadToolSources } from "./api";

export function useToolSources(threadId?: string) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["toolSources", threadId ?? null],
    queryFn: () => loadToolSources(threadId),
    // Slow on purpose: a source's state changes on a config edit or an
    // outage, not second to second.
    refetchInterval: 60_000,
  });
  return { view: data, isLoading, error };
}
