/**
 * Thread list and mutation hooks, without the streaming client.
 *
 * Split from ./hooks (Phase 2.5): the sidebar's recent-chat list is on every
 * page, and importing these from ./hooks pulled `useStream` and with it
 * @langchain/core (~370 KB) into every page, chat or not.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { fetch } from "../api/fetcher";
import { getBackendBaseURL } from "../config";

import type { OrganisePatch } from "./organise";
import {
  deleteThread,
  searchThreads,
  updateThreadState,
  type SearchParams,
} from "./rest";
import type { AgentThread } from "./types";

export function useThreads(
  params: SearchParams = {
    limit: 50,
    sortBy: "updated_at",
    sortOrder: "desc",
    select: ["thread_id", "updated_at", "values", "metadata"],
  },
) {
  return useQuery<AgentThread[]>({
    queryKey: ["threads", "search", params],
    queryFn: async () => {
      const maxResults = params.limit;
      const initialOffset = params.offset ?? 0;
      const DEFAULT_PAGE_SIZE = 50;

      // Preserve prior semantics: if a non-positive limit is explicitly provided,
      // delegate to a single search call with the original parameters.
      if (maxResults !== undefined && maxResults <= 0) {
        const response = await searchThreads(params);
        return response;
      }

      const pageSize =
        typeof maxResults === "number" && maxResults > 0
          ? Math.min(DEFAULT_PAGE_SIZE, maxResults)
          : DEFAULT_PAGE_SIZE;

      const threads: AgentThread[] = [];
      let offset = initialOffset;

      while (true) {
        if (typeof maxResults === "number" && threads.length >= maxResults) {
          break;
        }

        const currentLimit =
          typeof maxResults === "number"
            ? Math.min(pageSize, maxResults - threads.length)
            : pageSize;

        if (typeof maxResults === "number" && currentLimit <= 0) {
          break;
        }

        const response = await searchThreads({
          ...params,
          limit: currentLimit,
          offset,
        });

        threads.push(...response);

        if (response.length < currentLimit) {
          break;
        }

        offset += response.length;
      }

      return threads;
    },
    refetchOnWindowFocus: false,
  });
}

export function useDeleteThread() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ threadId }: { threadId: string }) => {
      await deleteThread(threadId);

      const response = await fetch(
        `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}`,
        {
          method: "DELETE",
        },
      );

      // 404: no local data was ever written (a thread that never ran), so
      // there is nothing left to delete. Not a failure.
      if (!response.ok && response.status !== 404) {
        const error = await response
          .json()
          .catch(() => ({ detail: "Failed to delete local thread data." }));
        throw new Error(error.detail ?? "Failed to delete local thread data.");
      }
    },
    onSuccess(_, { threadId }) {
      queryClient.setQueriesData(
        {
          queryKey: ["threads", "search"],
          exact: false,
        },
        (oldData: Array<AgentThread> | undefined) => {
          if (oldData == null) {
            return oldData;
          }
          return oldData.filter((t) => t.thread_id !== threadId);
        },
      );
    },
    onSettled() {
      void queryClient.invalidateQueries({ queryKey: ["threads", "search"] });
    },
  });
}

export function useRenameThread() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({
      threadId,
      title,
    }: {
      threadId: string;
      title: string;
    }) => {
      await updateThreadState(threadId, { title });
    },
    onSuccess(_, { threadId, title }) {
      queryClient.setQueriesData(
        {
          queryKey: ["threads", "search"],
          exact: false,
        },
        (oldData: Array<AgentThread>) => {
          return oldData.map((t) => {
            if (t.thread_id === threadId) {
              return {
                ...t,
                values: {
                  ...t.values,
                  title,
                },
              };
            }
            return t;
          });
        },
      );
    },
  });
}

/** A chat's own record (its metadata: archived, folder), by id. */
export function useThreadRecord(threadId: string | undefined) {
  return useQuery<{ thread_id: string; metadata: Record<string, unknown> }>({
    queryKey: ["threads", "record", threadId],
    enabled: !!threadId && threadId !== "new",
    retry: false,
    queryFn: async () => {
      const response = await fetch(
        `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId!)}`,
      );
      if (!response.ok) throw new Error(`thread ${response.status}`);
      return (await response.json()) as {
        thread_id: string;
        metadata: Record<string, unknown>;
      };
    },
  });
}

/** Archive, unarchive or file a chat (PATCH /api/threads/{id}: metadata). */
export function useOrganiseThread() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({
      threadId,
      patch,
    }: {
      threadId: string;
      patch: OrganisePatch;
    }) => {
      const response = await fetch(
        `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ metadata: patch }),
        },
      );
      if (!response.ok) {
        throw new Error(`Could not update the chat (${response.status}).`);
      }
    },
    onSettled() {
      void queryClient.invalidateQueries({ queryKey: ["threads"] });
    },
  });
}
