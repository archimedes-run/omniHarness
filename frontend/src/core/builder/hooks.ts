import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { PENDING_CONFIRMATIONS_KEY } from "@/core/confirmations/hooks";

import { dropBuilding, loadBuilderStatus, loadBuilding } from "./api";

export const builderKey = (threadId: string) => ["builder", threadId];

/** The chat's build, re-read when a run finishes (a builder tool call is
 *  what starts one, FR-002). */
export function useBuilding(
  threadId: string,
  enabled: boolean,
  running: boolean,
) {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: builderKey(threadId),
    queryFn: () => loadBuilding(threadId),
    enabled,
  });
  const wasRunning = useRef(running);
  useEffect(() => {
    if (wasRunning.current && !running) {
      void queryClient.invalidateQueries({ queryKey: builderKey(threadId) });
    }
    wasRunning.current = running;
  }, [running, threadId, queryClient]);
  return query.data?.building ?? null;
}

export function useDropBuilding(threadId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => dropBuilding(threadId),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: builderKey(threadId) });
      // Its open save card was refused: the card list changes too.
      void queryClient.invalidateQueries({
        queryKey: PENDING_CONFIRMATIONS_KEY,
      });
    },
  });
}

export function useBuilderStatus() {
  return useQuery({
    queryKey: ["builder", "status"],
    queryFn: () => loadBuilderStatus(),
  }).data;
}
