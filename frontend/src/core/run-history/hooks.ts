import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import * as api from "./api";

export function useRunHistorySettings() {
  const { data, error, isLoading } = useQuery({
    queryKey: ["runHistory", "settings"],
    queryFn: api.loadSettings,
  });
  return { settings: data, error, isLoading };
}

function useHistoryWrite<T, R>(fn: (input: T) => Promise<R>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSettled: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: ["runHistory"] }),
        queryClient.invalidateQueries({ queryKey: ["triggerRuns"] }),
      ]),
  });
}

export const useSaveRetention = () => useHistoryWrite(api.saveRetention);
export const useDeleteRunHistory = () =>
  useHistoryWrite((_: void) => api.deleteAllRuns());

/** One stored run with its full content, fetched when it is opened. */
export function useRun(id: string | null) {
  const { data, error, isLoading } = useQuery({
    queryKey: ["runHistory", "run", id],
    queryFn: () => api.loadRun(id!),
    enabled: !!id,
  });
  return { run: data, error, isLoading };
}
