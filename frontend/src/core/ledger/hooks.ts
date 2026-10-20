import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import * as api from "./api";

export function useProjects() {
  const { data, error, isLoading } = useQuery({
    queryKey: ["ledger", "projects"],
    queryFn: api.listProjects,
  });
  return { projects: data, error, isLoading };
}

export function useProject(id: string) {
  const { data, error, isLoading } = useQuery({
    queryKey: ["ledger", "project", id],
    queryFn: () => api.loadProject(id),
  });
  return { view: data, error, isLoading };
}

export function useThreadProjects(threadId: string | undefined) {
  const { data } = useQuery({
    queryKey: ["ledger", "thread", threadId],
    queryFn: () => api.threadProjects(threadId!),
    enabled: !!threadId,
  });
  return data;
}

/** Every write re-reads the ledger: counts, progress and links all move. */
export function useLedgerWrite<T, R>(fn: (input: T) => Promise<R>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["ledger"] }),
  });
}
