import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type { ToolSourcesView } from "./types";

export async function loadToolSources(
  threadId?: string,
): Promise<ToolSourcesView> {
  const query = threadId ? `?thread_id=${encodeURIComponent(threadId)}` : "";
  const response = await fetch(
    `${getBackendBaseURL()}/api/tool-sources${query}`,
  );
  return response.json() as Promise<ToolSourcesView>;
}

/** Load every MCP server again now; the states that load produced. */
export async function retryToolSources(): Promise<ToolSourcesView> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/tool-sources/retry`,
    { method: "POST" },
  );
  if (!response.ok) {
    throw new Error(`Retry failed (${response.status})`);
  }
  return response.json() as Promise<ToolSourcesView>;
}
