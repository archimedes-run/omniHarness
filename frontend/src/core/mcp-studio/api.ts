import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type { BuiltServer, BuiltServerList, StartBuildResponse } from "./types";

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

/** Describe a tool in words: an agent builds it and tests it in a sandbox. */
export async function startBuild(
  description: string,
): Promise<StartBuildResponse> {
  return json(
    await fetch(`${base()}/builds`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ description }),
    }),
  );
}

/** Approve the first real run and turn the server on. */
export async function approveAndEnable(id: string): Promise<BuiltServer> {
  return json(
    await fetch(`${base()}/servers/${id}/enable`, { method: "POST" }),
  );
}

export async function discardBuilt(id: string): Promise<void> {
  const response = await fetch(`${base()}/servers/${id}`, {
    method: "DELETE",
  });
  if (!response.ok && response.status !== 204) {
    throw new Error(`${response.status}: could not discard`);
  }
}
