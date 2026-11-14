import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

/**
 * "Memory off in this chat": a per-chat switch that keeps the agent from
 * reading the owner's memory and past chats. Set by the composer toggle, or
 * by the server when the owner's message asks for it (source "message").
 */
export interface ChatMemoryState {
  thread_id: string;
  memory_off: boolean;
  source: "toggle" | "message" | null;
}

export const chatMemoryKey = (threadId: string) => [
  "threads",
  threadId,
  "memory",
];

const memoryURL = (threadId: string) =>
  `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}/memory`;

/** The chat's state, or null when the chat has no record yet (404). */
export async function loadChatMemory(
  threadId: string,
): Promise<ChatMemoryState | null> {
  const response = await fetch(memoryURL(threadId));
  if (response.status === 404) return null;
  if (!response.ok)
    throw new Error(`Could not read the chat's memory (${response.status})`);
  return (await response.json()) as ChatMemoryState;
}

export async function setChatMemory(
  threadId: string,
  memoryOff: boolean,
): Promise<ChatMemoryState> {
  const response = await fetch(memoryURL(threadId), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ memory_off: memoryOff }),
  });
  if (!response.ok)
    throw new Error(`Could not change the chat's memory (${response.status})`);
  return (await response.json()) as ChatMemoryState;
}

/**
 * The chat's memory switch. An existing chat reads and writes the server; a
 * brand-new chat (no record until its first message) keeps the toggle locally,
 * and the page sends it with the first message as run context `memory_off`.
 * Re-read when a run finishes: the server may turn memory off by itself.
 */
export function useChatMemory(
  threadId: string,
  isNewThread: boolean,
  running: boolean,
) {
  const queryClient = useQueryClient();
  // The toggle before the chat has a record, for this chat only.
  const [pending, setPending] = useState<{ threadId: string } | null>(null);
  const query = useQuery({
    queryKey: chatMemoryKey(threadId),
    queryFn: () => loadChatMemory(threadId),
    enabled: !isNewThread && !!threadId,
  });
  // The first send created the chat (its id may change): the local toggle
  // carries over until the server's answer is in.
  const wasNew = useRef(isNewThread);
  useEffect(() => {
    if (wasNew.current && !isNewThread) {
      setPending((p) => (p ? { threadId } : p));
    }
    wasNew.current = isNewThread;
  }, [isNewThread, threadId]);
  const wasRunning = useRef(running);
  useEffect(() => {
    if (wasRunning.current && !running && !isNewThread) {
      void queryClient.invalidateQueries({ queryKey: chatMemoryKey(threadId) });
    }
    wasRunning.current = running;
  }, [running, isNewThread, threadId, queryClient]);
  const settled =
    !isNewThread && !running && !query.isFetching && query.data != null;
  // The server's record is the truth once it exists and no run is under way.
  useEffect(() => {
    if (settled) setPending(null);
  }, [settled]);
  const mutation = useMutation({
    mutationFn: (memoryOff: boolean) => setChatMemory(threadId, memoryOff),
    onSuccess: (state) => {
      queryClient.setQueryData(chatMemoryKey(threadId), state);
    },
  });
  const pendingOff = pending?.threadId === threadId;
  const memoryOff =
    !isNewThread && query.data && (settled || query.data.memory_off)
      ? query.data.memory_off
      : pendingOff;
  const noRecord = isNewThread || query.data === null;
  const setMemoryOff = (off: boolean) => {
    if (noRecord) setPending(off ? { threadId } : null);
    else mutation.mutate(off);
  };
  return {
    memoryOff,
    source: isNewThread ? null : (query.data?.source ?? null),
    setMemoryOff,
    /** Run context for the next send: only while the chat has no record. */
    sendContext:
      noRecord && pendingOff ? ({ memory_off: true } as const) : undefined,
    changing: mutation.isPending,
  };
}
