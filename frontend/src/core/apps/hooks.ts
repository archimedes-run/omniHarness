import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  approveApp,
  getApp,
  getAppPermissions,
  getAppPins,
  getAppVersions,
  getCatalog,
  getPendingApproval,
  listApps,
  listThreadApprovals,
  restoreApp,
  revokeApp,
  saveAppPins,
} from "./api";

const APPS = ["apps"] as const;
export const APP_PINS_KEY = ["appPins"] as const;

export function useApps() {
  const { data, error, isLoading } = useQuery({
    queryKey: APPS,
    queryFn: listApps,
  });
  return { apps: data, error, isLoading };
}

export function useApp(id: string) {
  return useQuery({ queryKey: [...APPS, id], queryFn: () => getApp(id) });
}

export function useAppVersions(id: string, enabled: boolean) {
  return useQuery({
    queryKey: [...APPS, id, "versions"],
    queryFn: () => getAppVersions(id),
    enabled,
  });
}

export function useAppPermissions(id: string, enabled: boolean) {
  return useQuery({
    queryKey: [...APPS, id, "permissions"],
    queryFn: () => getAppPermissions(id),
    enabled,
  });
}

export function usePendingApproval(id: string, enabled: boolean) {
  return useQuery({
    queryKey: [...APPS, id, "approval"],
    queryFn: () => getPendingApproval(id),
    enabled,
  });
}

export function useThreadApprovals(threadId: string | undefined) {
  return useQuery({
    queryKey: ["appApprovals", threadId],
    queryFn: () => listThreadApprovals(threadId!),
    enabled: !!threadId,
    retry: false,
  });
}

export function useAppCatalog(enabled = true) {
  return useQuery({
    queryKey: ["appCatalog"],
    queryFn: getCatalog,
    staleTime: 5 * 60_000,
    enabled,
  });
}

/** Any write re-reads every app view: status, versions, grants, the card. */
function useAppsWrite<T, R>(fn: (input: T) => Promise<R>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSettled: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: APPS }),
        client.invalidateQueries({ queryKey: ["appApprovals"] }),
      ]),
  });
}

export const useApproveApp = () =>
  useAppsWrite((input: { id: string; manifestHash: string; cardId: string }) =>
    approveApp(input.id, input.manifestHash, input.cardId),
  );

export const useRestoreApp = () =>
  useAppsWrite(
    (input: { id: string; toVersion: number; baseVersion: number }) =>
      restoreApp(input.id, input.toVersion, input.baseVersion),
  );

export const useRevokeApp = () => useAppsWrite((id: string) => revokeApp(id));

export function useAppPins() {
  const { data, error } = useQuery({
    queryKey: APP_PINS_KEY,
    queryFn: getAppPins,
    retry: false,
  });
  return { pins: data, error };
}

export function useSaveAppPins() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: saveAppPins,
    onSuccess: (pins) => client.setQueryData(APP_PINS_KEY, pins),
    onSettled: () => client.invalidateQueries({ queryKey: APPS }),
  });
}
