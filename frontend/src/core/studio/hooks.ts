import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import * as api from "./api";
import type { ScheduleWrite } from "./types";

export function useStudioOptions() {
  const { data, error, isLoading } = useQuery({
    queryKey: ["studio", "options"],
    queryFn: api.loadStudioOptions,
    staleTime: 60_000,
  });
  return { options: data, error, isLoading };
}

export function useCustomSkill(name: string | null) {
  const { data, error, isLoading } = useQuery({
    queryKey: ["skills", "custom", name],
    queryFn: () => api.loadCustomSkill(name!),
    enabled: !!name,
  });
  return { skill: data, error, isLoading };
}

export function useSkillFiles(name: string | null) {
  const { data, error, isLoading } = useQuery({
    queryKey: ["skills", "files", name],
    queryFn: () => api.loadSkillFiles(name!),
    enabled: !!name,
  });
  return { files: data?.files, error, isLoading };
}

export function useAgentRuns(name: string | null) {
  const { data, error, isLoading } = useQuery({
    queryKey: ["studio", "runs", name],
    queryFn: () => api.loadAgentRuns(name!),
    enabled: !!name,
    refetchInterval: 60_000,
  });
  return { runs: data, error, isLoading };
}

export function useAutonomy(name: string | null) {
  const { data, error, isLoading } = useQuery({
    queryKey: ["studio", "autonomy", name],
    queryFn: () => api.loadAutonomy(name!),
    enabled: !!name,
  });
  return { autonomy: data, error, isLoading };
}

export function useGrantUses(name: string | null) {
  const { data, error } = useQuery({
    queryKey: ["studio", "grant-uses", name],
    queryFn: () => api.loadGrantUses(name!),
    enabled: !!name,
    refetchInterval: 60_000,
  });
  return { uses: data, error };
}

type ScheduleChange =
  | { kind: "create"; body: ScheduleWrite }
  | { kind: "update"; ruleId: string; body: ScheduleWrite }
  | { kind: "delete"; ruleId: string; version: string };

/** Create, change or delete one of an agent's schedules. Afterwards every
 * view of the rules re-reads: the agent's runs, Automations and Home. */
export function useScheduleWrite(name: string | null) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (change: ScheduleChange) => {
      if (!name) throw new Error("Save the agent first.");
      if (change.kind === "create")
        return api.createSchedule(name, change.body);
      if (change.kind === "update")
        return api.updateSchedule(name, change.ruleId, change.body);
      return api.deleteSchedule(name, change.ruleId, change.version);
    },
    onSettled: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: ["studio", "runs"] }),
        client.invalidateQueries({ queryKey: ["triggerRules"] }),
        client.invalidateQueries({ queryKey: ["home", "upcoming"] }),
      ]),
  });
}
