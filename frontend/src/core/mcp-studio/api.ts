import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type { BuiltServerList } from "./types";

async function json<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // the status line is all there is
    }
    throw new Error(`${response.status}: ${detail}`);
  }
  return response.json() as Promise<T>;
}

const base = () => `${getBackendBaseURL()}/api/mcp-studio`;

/** The servers agents built, each with where it is in words. */
export async function listBuiltServers(): Promise<BuiltServerList> {
  return json(await fetch(`${base()}/servers`));
}

export async function discardBuilt(id: string): Promise<void> {
  const response = await fetch(`${base()}/servers/${id}`, {
    method: "DELETE",
  });
  if (!response.ok && response.status !== 204) {
    throw new Error(`${response.status}: could not discard`);
  }
}
