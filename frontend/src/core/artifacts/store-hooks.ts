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
  ArtifactsApiError,
  importChatFile,
  setSaved,
  type ArtifactDetail,
  type ArtifactSummary,
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

// -- Save, unsave, import (owner clicks only) --------------------------------

const SAVE_UNAVAILABLE = [...ARTIFACTS_KEY, "save-unavailable"] as const;

/** True once a save route answered 404: the gateway has no save routes,
 * so the Save and Download controls hide (one request, no retries). */
export function useSaveUnavailable(): boolean {
  const { data } = useQuery({
    queryKey: SAVE_UNAVAILABLE,
    queryFn: () => false,
    staleTime: Infinity,
    gcTime: Infinity,
  });
  return data === true;
}

function isMissingRoute(err: unknown): boolean {
  return (
    err instanceof ArtifactsApiError &&
    err.status === 404 &&
    err.code !== "artifact_not_found"
  );
}

/** Save or unsave, optimistically: the detail and every list update at
 * once and roll back if the gateway refuses. */
export function useSaveArtifact(id: string) {
  const client = useQueryClient();
  const detailKey = [...ARTIFACTS_KEY, "artifact", id];
  return useMutation({
    mutationFn: (saved: boolean) => setSaved(id, saved),
    retry: false,
    onMutate: async (saved: boolean) => {
      await client.cancelQueries({ queryKey: detailKey });
      const before = client.getQueryData<ArtifactDetail>(detailKey);
      if (before) client.setQueryData(detailKey, { ...before, saved });
      return { before };
    },
    onError: (err, _saved, ctx) => {
      if (ctx?.before) client.setQueryData(detailKey, ctx.before);
      if (isMissingRoute(err)) client.setQueryData(SAVE_UNAVAILABLE, true);
    },
    onSuccess: (summary) => {
      const before = client.getQueryData<ArtifactDetail>(detailKey);
      if (before) client.setQueryData(detailKey, { ...before, ...summary });
      // Lists change in place (an item saved from "still in their chats"
      // stays, marked Saved) and refetch on the next visit.
      const isList = (q: { queryKey: readonly unknown[] }) =>
        q.queryKey[0] === ARTIFACTS_KEY[0] && q.queryKey[1] === "list";
      client.setQueriesData<{ artifacts: ArtifactSummary[] }>(
        { predicate: isList },
        (old) =>
          old && {
            ...old,
            artifacts: old.artifacts.map((a) =>
              a.id === id ? { ...a, saved: summary.saved } : a,
            ),
          },
      );
      void client.invalidateQueries({ predicate: isList, refetchType: "none" });
    },
  });
}

/** Save a chat file (or a coding job's published site) into the store. */
export function useImportChatFile(threadId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (path: string) => importChatFile(threadId, path),
    retry: false,
    onError: (err) => {
      if (isMissingRoute(err)) client.setQueryData(SAVE_UNAVAILABLE, true);
    },
    onSettled: () =>
      client.invalidateQueries({
        predicate: (q) =>
          q.queryKey[0] === ARTIFACTS_KEY[0] && q.queryKey[1] === "list",
      }),
  });
}
