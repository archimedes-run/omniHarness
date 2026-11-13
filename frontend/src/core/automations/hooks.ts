import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createRule,
  deleteRule,
  loadRuleVersions,
  loadTemplates,
  replaceRule,
  setRuleEnabled,
  undoRule,
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
        queryClient.invalidateQueries({ queryKey: ["ruleVersions"] }),
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

/** One rule's version history (Spec 010). Not retried: a 404 means the rule
 * has neither a history nor a place in the rules file. */
export function useRuleVersions(id: string | null) {
  return useQuery({
    queryKey: ["ruleVersions", id],
    queryFn: () => loadRuleVersions(id!),
    enabled: !!id,
    retry: false,
  });
}

/** Restore a version of a rule as a new version; refreshes everything that
 * shows the rules (the board, its runs, Studio's schedules, the history). */
export function useUndoRule() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      toVersion,
      baseVersion,
      via,
    }: {
      id: string;
      toVersion: number;
      baseVersion: number;
      via: "page" | "studio";
    }) => undoRule(id, toVersion, baseVersion, via),
    onSettled: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: ["triggerRules"] }),
        queryClient.invalidateQueries({ queryKey: ["triggerRuns"] }),
        queryClient.invalidateQueries({ queryKey: ["ruleVersions"] }),
        queryClient.invalidateQueries({ queryKey: ["studio", "runs"] }),
      ]),
  });
}
