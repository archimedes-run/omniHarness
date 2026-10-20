import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { countsTowardBadge } from "../inbox/hooks";
import type { InboxAlerts } from "../inbox/types";

import * as api from "./api";
import { alertKey, startOfDay } from "./logic";

const DISMISSALS = ["home", "dismissals"];

export function useHomeDismissals() {
  const { data, error, isLoading } = useQuery({
    queryKey: DISMISSALS,
    queryFn: api.loadDismissals,
  });
  return { dismissals: data, error, isLoading };
}

/**
 * Dismiss alerts on the server. The alert list (and so the New chat badge)
 * re-reads afterwards; until then the alerts are marked dismissed in the
 * cache, so they leave the screen at once.
 */
export function useDismissAlerts() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (keys: string[]) => api.dismiss({ kind: "alert", keys }),
    onMutate: (keys) => {
      client.setQueryData<InboxAlerts>(["inboxAlerts"], (old) => {
        if (!old) return old;
        const newly = old.alerts.filter(
          (a) => countsTowardBadge(a) && keys.includes(alertKey(a)),
        ).length;
        return {
          ...old,
          waiting_count: Math.max(0, old.waiting_count - newly),
          alerts: old.alerts.map((a) =>
            keys.includes(alertKey(a)) ? { ...a, dismissed: true } : a,
          ),
        };
      });
    },
    onSuccess: (saved) => client.setQueryData(DISMISSALS, saved),
    onSettled: () => client.invalidateQueries({ queryKey: ["inboxAlerts"] }),
  });
}

export function useDismissNamePrompt() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api.dismiss({ kind: "name-prompt" }),
    onSuccess: (saved) => client.setQueryData(DISMISSALS, saved),
  });
}

export function useUpcoming() {
  const { data, error, isLoading } = useQuery({
    queryKey: ["home", "upcoming"],
    queryFn: api.loadUpcoming,
    refetchInterval: 60_000,
  });
  return { upcoming: data, error, isLoading };
}

export function useMovedToday(now: Date) {
  const since = startOfDay(now).toISOString();
  const { data, error, isLoading } = useQuery({
    queryKey: ["home", "today", since],
    queryFn: () => api.loadMovedToday(since),
    refetchInterval: 60_000,
  });
  return { moved: data, error, isLoading };
}
