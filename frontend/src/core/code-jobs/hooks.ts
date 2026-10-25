import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  type CodeJobPayload,
  CodeJobNotFound,
  loadCodeJobByCall,
  stopCodeJob,
} from "./api";

/** Steps are fetched incrementally (`after` the last seen) and appended. */
export function useCodeJob({
  threadId,
  toolCallId,
  waiting,
}: {
  threadId: string;
  toolCallId: string;
  /** The tool call has no result yet: keep looking for the job to appear. */
  waiting: boolean;
}) {
  const queryClient = useQueryClient();
  const key = ["code-job", threadId, toolCallId];
  const [mountedAt] = useState(() => Date.now());
  return useQuery<CodeJobPayload, Error>({
    queryKey: key,
    queryFn: async () => {
      const previous = queryClient.getQueryData<CodeJobPayload>(key);
      const after = previous?.steps.at(-1)?.seq ?? 0;
      const next = await loadCodeJobByCall({ threadId, toolCallId, after });
      if (previous?.job.id === next.job.id) {
        return { ...next, steps: [...previous.steps, ...next.steps] };
      }
      return next;
    },
    retry: false,
    refetchOnWindowFocus: false,
    refetchInterval: (query) => {
      if (query.state.error instanceof CodeJobNotFound) {
        // Look often at first, then back off (a run that died never returns).
        const age = Date.now() - (query.state.dataUpdatedAt || mountedAt);
        return waiting ? (age < 120_000 ? 1500 : 5000) : false;
      }
      return query.state.data?.job.status === "running" ? 1000 : false;
    },
  });
}

export function useStopCodeJob({
  threadId,
  toolCallId,
}: {
  threadId: string;
  toolCallId: string;
}) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) => stopCodeJob({ threadId, jobId }),
    onSettled: () => {
      void queryClient.invalidateQueries({
        queryKey: ["code-job", threadId, toolCallId],
      });
    },
  });
}
