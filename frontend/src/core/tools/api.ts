import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

export type ToolCatalogItem = {
  tool_id: string; // namespaced: local:<server> | connector:<SLUG>
  name: string;
  description: string;
  source: "local" | "connector";
  toolkit: string | null;
  icon: string | null;
  category: string;
  connected: boolean;
  pinned: boolean;
};

export type ToolCatalog = {
  items: ToolCatalogItem[];
  categories: string[];
};

export type ThreadSelection = {
  thread_id: string;
  sources: string[];
  pinned: string[];
};

export type ToolCount = {
  count: number;
  cap: number;
  over_cap: boolean;
};

export async function getToolsCatalog(): Promise<ToolCatalog> {
  const res = await fetch(`${getBackendBaseURL()}/api/tools/catalog`, {
    credentials: "include",
  });
  if (!res.ok) throw new Error(`catalog failed: ${res.status}`);
  return res.json();
}

export async function getThreadSelection(
  threadId: string,
): Promise<ThreadSelection> {
  const res = await fetch(
    `${getBackendBaseURL()}/api/threads/${threadId}/tools`,
    { credentials: "include" },
  );
  if (!res.ok) throw new Error(`get selection failed: ${res.status}`);
  return res.json();
}

export async function putThreadSelection(
  threadId: string,
  sources: string[],
): Promise<ThreadSelection> {
  const res = await fetch(
    `${getBackendBaseURL()}/api/threads/${threadId}/tools`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ sources }),
    },
  );
  if (!res.ok) throw new Error(`put selection failed: ${res.status}`);
  return res.json();
}

export async function getThreadToolCount(threadId: string): Promise<ToolCount> {
  const res = await fetch(
    `${getBackendBaseURL()}/api/threads/${threadId}/tools/count`,
    { credentials: "include" },
  );
  if (!res.ok) throw new Error(`count failed: ${res.status}`);
  return res.json();
}
