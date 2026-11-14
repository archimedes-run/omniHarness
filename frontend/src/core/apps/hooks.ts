import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  AppsApiError,
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

/**
 * Retry a failed read twice, except a 4xx: a gateway without the Apps routes
 * (404) or a refusal will answer the same again. The sidebar reads apps and
 * pins on every page, so a missing route must cost one request, not four.
 */
function retryUnless4xx(count: number, error: Error): boolean {
  if (
    error instanceof AppsApiError &&
    error.status >= 400 &&
    error.status < 500
  ) {
    return false;
  }
  return count < 2;
}
const QUIET = { retry: retryUnless4xx, staleTime: 60_000 } as const;
export const APP_PINS_KEY = ["appPins"] as const;

export function useApps() {
  const { data, error, isLoading } = useQuery({
    queryKey: APPS,
    queryFn: listApps,
    ...QUIET,
  });
  return { apps: data, error, isLoading };
}

export function useApp(id: string) {
  return useQuery({
    queryKey: [...APPS, id],
    queryFn: () => getApp(id),
    retry: retryUnless4xx,
  });
}

export function useAppVersions(id: string, enabled: boolean) {
  return useQuery({
    queryKey: [...APPS, id, "versions"],
    queryFn: () => getAppVersions(id),
    enabled,
    retry: retryUnless4xx,
  });
}

export function useAppPermissions(id: string, enabled: boolean) {
  return useQuery({
    queryKey: [...APPS, id, "permissions"],
    queryFn: () => getAppPermissions(id),
    enabled,
    retry: retryUnless4xx,
  });
}

export function usePendingApproval(id: string, enabled: boolean) {
  return useQuery({
    queryKey: [...APPS, id, "approval"],
    queryFn: () => getPendingApproval(id),
    enabled,
    retry: retryUnless4xx,
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
    retry: retryUnless4xx,
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
    ...QUIET,
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
