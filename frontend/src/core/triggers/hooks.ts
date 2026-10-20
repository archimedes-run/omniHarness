import { useQuery } from "@tanstack/react-query";

import { loadFirings, loadRules, loadRuns } from "./api";

export function useTriggerRules() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["triggerRules"],
    queryFn: loadRules,
    refetchInterval: 30_000,
  });
  return { view: data, isLoading, error };
}

export function useTriggerFirings() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["triggerFirings"],
    queryFn: loadFirings,
    refetchInterval: 30_000,
  });
  return { view: data, isLoading, error };
}

/** One automation's runs, worded by the server from its audit records. */
export function useTriggerRuns(ruleId: string | null) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["triggerRuns", ruleId],
    queryFn: () => loadRuns(ruleId!),
    enabled: !!ruleId,
    refetchInterval: 30_000,
  });
  return { view: data, isLoading, error };
}
