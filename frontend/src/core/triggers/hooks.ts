import { useQuery } from "@tanstack/react-query";

import { loadFirings, loadRules } from "./api";

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
