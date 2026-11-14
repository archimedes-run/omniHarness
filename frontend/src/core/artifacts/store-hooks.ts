import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  archiveArtifact,
  deleteArtifact,
  duplicateArtifact,
  getArtifact,
  getUsage,
  getVersion,
  listArtifacts,
  patchArtifact,
  restoreVersion,
  saveVersion,
  type ListQuery,
} from "./store-api";
import { retryUnless4xx } from "./store-logic";

export const ARTIFACTS_KEY = ["artifact-store"] as const;

export function useArtifactList(query: ListQuery) {
  return useQuery({
    queryKey: [...ARTIFACTS_KEY, "list", query],
    queryFn: () => listArtifacts(query),
    retry: retryUnless4xx,
    staleTime: 15_000,
    refetchOnWindowFocus: false,
  });
}

export function useStoreArtifact(id: string | null) {
  return useQuery({
    queryKey: [...ARTIFACTS_KEY, "artifact", id],
    queryFn: () => getArtifact(id!),
    enabled: !!id,
    retry: retryUnless4xx,
    staleTime: 10_000,
    refetchOnWindowFocus: false,
  });
}

/** A version never changes: read once. */
export function useArtifactVersion(id: string | null, n: number | null) {
  return useQuery({
    queryKey: [...ARTIFACTS_KEY, "version", id, n],
    queryFn: () => getVersion(id!, n!),
    enabled: !!id && !!n,
    retry: retryUnless4xx,
    staleTime: Infinity,
    gcTime: 10 * 60_000,
    refetchOnWindowFocus: false,
  });
}

export function useArtifactUsage(enabled = true) {
  return useQuery({
    queryKey: [...ARTIFACTS_KEY, "usage"],
    queryFn: getUsage,
    enabled,
    retry: retryUnless4xx,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });
}

function useInvalidate() {
  const client = useQueryClient();
  return () =>
    client.invalidateQueries({
      predicate: (q) =>
        q.queryKey[0] === ARTIFACTS_KEY[0] && q.queryKey[1] !== "version",
    });
}

export function useArtifactActions(id: string) {
  const invalidate = useInvalidate();
  const opts = { onSettled: invalidate };
  return {
    patch: useMutation({
      mutationFn: (body: { title?: string; pinned?: boolean }) =>
        patchArtifact(id, body),
      ...opts,
    }),
    archive: useMutation({
      mutationFn: (archived: boolean) => archiveArtifact(id, archived),
      ...opts,
    }),
    save: useMutation({
      mutationFn: (body: {
        base_version: number;
        content: string;
        language?: string;
      }) => saveVersion(id, body),
      ...opts,
    }),
    restore: useMutation({
      mutationFn: (v: { version: number; base: number }) =>
        restoreVersion(id, v.version, v.base),
      ...opts,
    }),
    duplicate: useMutation({
      mutationFn: (version?: number) => duplicateArtifact(id, version),
      ...opts,
    }),
    remove: useMutation({
      mutationFn: (versionCount: number) => deleteArtifact(id, versionCount),
      ...opts,
    }),
  };
}
