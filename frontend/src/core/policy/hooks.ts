import { useMutation, useQuery } from "@tanstack/react-query";

import { checkTier, loadAudit, loadRules } from "./api";

export function usePolicyRules() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["policyRules"],
    queryFn: loadRules,
    refetchInterval: 30_000,
  });
  return { rules: data, isLoading, error };
}

export function useTier3Audit() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["policyAudit"],
    queryFn: loadAudit,
    refetchInterval: 30_000,
  });
  return { executions: data, isLoading, error };
}

/** A tier check runs nothing (FR-025) — it is still a request, so a mutation
 *  driven by the form, not a query that fires on every keystroke. */
export function useTierCheck() {
  return useMutation({
    mutationFn: ({ tool, args }: { tool: string; args: string }) =>
      checkTier(tool, args),
  });
}
