import { useQuery } from "@tanstack/react-query";

import { loadSessions } from "./api";

export function useSessions() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["codingSessions"],
    queryFn: loadSessions,
    // Sessions move in seconds; the watcher reconciles every few.
    refetchInterval: 15_000,
  });
  return { view: data, isLoading, error };
}
