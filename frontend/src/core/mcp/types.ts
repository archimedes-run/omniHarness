export interface MCPServerConfig extends Record<string, unknown> {
  enabled: boolean;
  description: string;
}

export interface MCPConfig {
  mcp_servers: Record<string, MCPServerConfig>;
}

export type ComposioConnectionStatus =
  | "not_connected"
  | "pending"
  | "connected"
  | "error";

export interface ComposioToolkit {
  slug: string;
  name: string;
  icon: string;
  category: string;
  description: string;
  status: ComposioConnectionStatus;
  account_display: string | null;
}

export interface ComposioConnection {
  toolkit: string;
  status: ComposioConnectionStatus;
  account_display: string | null;
  composio_connection_id: string | null;
  created_at: string;
}
