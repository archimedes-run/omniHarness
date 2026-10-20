import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createRule,
  deleteRule,
  loadTemplates,
  replaceRule,
  setRuleEnabled,
  type RuleDoc,
} from "./api";

export function useAutomationTemplates() {
  const { data, error } = useQuery({
    queryKey: ["automationTemplates"],
    queryFn: loadTemplates,
    staleTime: Infinity,
  });
  return { templates: data, error };
}

/** Every write re-reads the rules afterwards: the version changed, and the
 * page must show what the engine will now run. */
function useRuleWrite<T>(fn: (input: T) => Promise<{ version: string }>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSettled: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: ["triggerRules"] }),
        queryClient.invalidateQueries({ queryKey: ["triggerRuns"] }),
      ]),
  });
}

export const useSaveRule = () =>
  useRuleWrite(
    ({
      rule,
      version,
      create,
    }: {
      rule: RuleDoc;
      version: string;
      create: boolean;
    }) => (create ? createRule(rule, version) : replaceRule(rule, version)),
  );
export const useSetRuleEnabled = () =>
  useRuleWrite(
    ({
      id,
      enabled,
      version,
    }: {
      id: string;
      enabled: boolean;
      version: string;
    }) => setRuleEnabled(id, enabled, version),
  );
export const useDeleteRule = () =>
  useRuleWrite(({ id, version }: { id: string; version: string }) =>
    deleteRule(id, version),
  );
