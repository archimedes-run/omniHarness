import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type { ComposioConnection, ComposioToolkit, MCPConfig } from "./types";

export async function loadMCPConfig() {
  const response = await fetch(`${getBackendBaseURL()}/api/mcp/config`);
  return response.json() as Promise<MCPConfig>;
}

export async function updateMCPConfig(config: MCPConfig) {
  const response = await fetch(`${getBackendBaseURL()}/api/mcp/config`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(config),
  });
  return response.json();
}

// ---------------------------------------------------------------------------
// Composio 1-click connector
// ---------------------------------------------------------------------------

export async function getComposioCatalog(): Promise<ComposioToolkit[]> {
  const res = await fetch(`${getBackendBaseURL()}/api/composio/catalog`);
  const data = (await res.json()) as { toolkits: ComposioToolkit[] };
  return data.toolkits;
}

export async function initiateComposioConnection(
  toolkit: string,
  redirectUrl: string,
): Promise<
  | { composio_redirect_url: string; connection_id: string }
  | { status: "already_connected" }
> {
  const res = await fetch(
    `${getBackendBaseURL()}/api/composio/connections/initiate`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ toolkit, redirect_url: redirectUrl }),
    },
  );
  return res.json();
}

export async function getComposioConnectionStatus(toolkit: string): Promise<{
  status: string;
  toolkit: string;
  account_display: string | null;
}> {
  const res = await fetch(
    `${getBackendBaseURL()}/api/composio/connections/${toolkit}`,
  );
  return res.json();
}

export async function listComposioConnections(): Promise<ComposioConnection[]> {
  const res = await fetch(`${getBackendBaseURL()}/api/composio/connections`);
  const data = (await res.json()) as { connections: ComposioConnection[] };
  return data.connections;
}

export async function disconnectComposioToolkit(
  toolkit: string,
): Promise<void> {
  await fetch(`${getBackendBaseURL()}/api/composio/connections/${toolkit}`, {
    method: "DELETE",
  });
}
