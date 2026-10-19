/**
 * The four thread calls the sidebar makes, over plain REST.
 *
 * The LangGraph SDK's `Client` imports its streaming module, which imports
 * @langchain/core/messages: ~370 KB of JavaScript on every page, for a list
 * of chat titles (Phase 2.5). These send exactly what the SDK sends, to the
 * same LangGraph-compatible routes, through the app's fetcher (credentials
 * and CSRF). Streaming a run still uses the SDK, on chat pages only.
 */
import type { ThreadsClient } from "@langchain/langgraph-sdk/client";

import { fetch } from "../api/fetcher";
import { getLangGraphBaseURL } from "../config";

import type { AgentThread, AgentThreadState } from "./types";

type SearchParams = Parameters<ThreadsClient["search"]>[0];

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const base = getLangGraphBaseURL().replace(/\/+$/, "");
  const res = await fetch(`${base}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!res.ok) {
    throw new Error(
      `${init?.method ?? "GET"} ${path}: ${res.status} ${res.statusText}`,
    );
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

export function searchThreads(
  query: SearchParams = {},
): Promise<AgentThread[]> {
  return call<AgentThread[]>("/threads/search", {
    method: "POST",
    body: JSON.stringify({
      metadata: query?.metadata,
      ids: query?.ids,
      limit: query?.limit ?? 10,
      offset: query?.offset ?? 0,
      status: query?.status,
      sort_by: query?.sortBy,
      sort_order: query?.sortOrder,
      select: query?.select,
      values: query?.values,
    }),
  });
}

export function getThreadState(
  threadId: string,
): Promise<{ values: AgentThreadState }> {
  return call(`/threads/${encodeURIComponent(threadId)}/state`);
}

export function updateThreadState(
  threadId: string,
  values: Partial<AgentThreadState>,
): Promise<unknown> {
  return call(`/threads/${encodeURIComponent(threadId)}/state`, {
    method: "POST",
    body: JSON.stringify({ values }),
  });
}

export function deleteThread(threadId: string): Promise<unknown> {
  return call(`/threads/${encodeURIComponent(threadId)}`, { method: "DELETE" });
}
