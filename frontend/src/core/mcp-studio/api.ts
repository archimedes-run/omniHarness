import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type {
  ApprovalPacket,
  BuildEvent,
  BuiltServer,
  BuiltServerList,
  StartBuildResponse,
} from "./types";

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

/** What the approval screen shows: the full code, its hash, the outbound
 * hosts and the tools, plus the single-use token that proves it was shown. */
export async function getApprovalPacket(id: string): Promise<ApprovalPacket> {
  return json(await fetch(`${base()}/servers/${id}/approval`));
}

/** Approve the code you were shown (named by its hash, proven by the view
 * token) and turn it on. The gateway refuses if the code changed since. */
export async function approveAndEnable(
  id: string,
  codeSha256: string,
  viewToken: string,
  toolTiers: Record<string, 1 | 2 | 3> = {},
): Promise<BuiltServer> {
  return json(
    await fetch(`${base()}/servers/${id}/enable`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        code_sha256: codeSha256,
        view_token: viewToken,
        tool_tiers: toolTiers,
      }),
    }),
  );
}

export async function discardBuilt(id: string): Promise<void> {
  const response = await fetch(`${base()}/servers/${id}`, {
    method: "DELETE",
  });
  if (!response.ok && response.status !== 204) {
    // e.g. 502: a container could not be removed, so nothing was deleted.
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // the status line is all there is
    }
    throw new Error(`Not deleted: ${detail}`);
  }
}

/** What the gateway retired or turned off on its own, newest first. */
export async function listBuildEvents(): Promise<{ events: BuildEvent[] }> {
  return json(await fetch(`${base()}/events`));
}
