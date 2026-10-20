"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo } from "react";

import { listAgents } from "@/core/agents/api";
import { attachThread, detachLink } from "@/core/ledger/api";
import {
  useLedgerWrite,
  useProjects,
  useThreadProjects,
} from "@/core/ledger/hooks";
import { loadSkills } from "@/core/skills/api";
import { useToolSources } from "@/core/tool-sources/hooks";
import {
  getThreadSelection,
  getThreadToolCount,
  getToolsCatalog,
  putThreadSelection,
  type ThreadSelection,
} from "@/core/tools/api";
import { listUploadedFiles } from "@/core/uploads/api";

import { integrationRows, type IntegrationRow } from "./logic";

/**
 * The thread's tool selection, the same one the old "Tools for this chat"
 * panel edited: GET/PUT /api/threads/{id}/tools. The bar shows it as chips
 * and the picker's Integrations tab toggles it.
 */
export function useThreadIntegrations(threadId: string) {
  const queryClient = useQueryClient();
  const catalog = useQuery({
    queryKey: ["tools", "catalog"],
    queryFn: getToolsCatalog,
    staleTime: 60_000,
  });
  const selection = useQuery({
    queryKey: ["tools", "thread", threadId],
    queryFn: () => getThreadSelection(threadId),
    enabled: !!threadId,
  });
  const count = useQuery({
    queryKey: ["tools", "thread", threadId, "count"],
    queryFn: () => getThreadToolCount(threadId),
    enabled: !!threadId,
  });
  const { view, error: sourcesError } = useToolSources(threadId);

  const save = useMutation({
    mutationFn: (sources: string[]) => putThreadSelection(threadId, sources),
    onMutate: async (sources) => {
      const key = ["tools", "thread", threadId];
      await queryClient.cancelQueries({ queryKey: key, exact: true });
      const previous = queryClient.getQueryData<ThreadSelection>(key);
      if (previous) {
        queryClient.setQueryData<ThreadSelection>(key, {
          ...previous,
          sources,
        });
      }
      return { previous };
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.previous) {
        queryClient.setQueryData(["tools", "thread", threadId], ctx.previous);
      }
    },
    onSuccess: (saved) => {
      queryClient.setQueryData(["tools", "thread", threadId], saved);
    },
    onSettled: () => {
      void queryClient.invalidateQueries({
        queryKey: ["tools", "thread", threadId, "count"],
      });
      void queryClient.invalidateQueries({ queryKey: ["toolSources"] });
    },
  });

  const selected = useMemo(
    () => new Set(selection.data?.sources ?? []),
    [selection.data],
  );
  const pinned = useMemo(
    () => new Set(selection.data?.pinned ?? []),
    [selection.data],
  );
  const rows: IntegrationRow[] = useMemo(
    () =>
      integrationRows(
        catalog.data?.items ?? [],
        sourcesError ? undefined : view?.sources,
        selected,
        pinned,
        view?.connectors_available ?? true,
      ),
    [catalog.data, view, sourcesError, selected, pinned],
  );

  const overCap = !!count.data && count.data.count >= count.data.cap;

  const setSelected = useCallback(
    (id: string, on: boolean) => {
      if (pinned.has(id)) return;
      const next = new Set(selected);
      if (on) next.add(id);
      else next.delete(id);
      save.mutate([...next]);
    },
    [pinned, selected, save],
  );

  return {
    rows,
    loading: catalog.isLoading || selection.isLoading,
    /** The catalog or the selection could not be read: said, not hidden. */
    error: catalog.error ?? selection.error ?? null,
    /** Live status could not be read: every row says "Status unknown". */
    statusError: sourcesError ?? null,
    count: count.data ?? null,
    /** False without a Composio key: no connector rows, one line instead. */
    connectorsAvailable: view?.connectors_available ?? true,
    overCap,
    saveError: save.error,
    setSelected,
  };
}

export function useChatProjects(threadId: string, title?: string) {
  const attached = useThreadProjects(threadId);
  const { projects, isLoading } = useProjects();
  const attach = useLedgerWrite((projectId: string) =>
    attachThread(projectId, threadId, title),
  );
  const detach = useLedgerWrite(detachLink);
  return {
    attached: attached ?? [],
    projects: projects ?? [],
    loading: isLoading,
    attach,
    detach,
  };
}

/** The agents the user can call in; loaded only once something asks. */
export function useAgentChoices(enabled: boolean) {
  const { data, error, isLoading } = useQuery({
    queryKey: ["agents"],
    queryFn: listAgents,
    enabled,
  });
  return { agents: data ?? [], error, isLoading };
}

/** Enabled skills only: a disabled skill is not in the agent's prompt. */
export function useSkillChoices(enabled: boolean) {
  const { data, error, isLoading } = useQuery({
    queryKey: ["skills"],
    queryFn: loadSkills,
    enabled,
  });
  return {
    skills: (data ?? []).filter((s) => s.enabled),
    error,
    isLoading,
  };
}

/** Files already uploaded to this chat; read only when the Files tab asks. */
export function useChatUploads(threadId: string, enabled: boolean) {
  const { data } = useQuery({
    queryKey: ["uploads", "list", threadId],
    queryFn: () => listUploadedFiles(threadId),
    enabled: enabled && !!threadId,
  });
  return data?.files ?? [];
}
