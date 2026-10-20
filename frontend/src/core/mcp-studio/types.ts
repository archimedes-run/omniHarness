/** Mirrors app/gateway/routers/mcp_studio.py and app/gateway/mcp_build_flow.py. */

/** Where a built server is, in words (Feature 006, MCP Suite > Build). */
export type BuildState =
  | "drafting"
  | "building"
  | "tests_failed"
  | "awaiting_approval"
  | "turning_on"
  | "turn_on_failed"
  | "enabled"
  | "off"
  | "stalled";

export interface BuildStep {
  /** done: it happened; failed: it did not; waiting: on you or on time. */
  status: "done" | "failed" | "waiting";
  text: string;
}

export interface BuiltServer {
  id: string;
  name: string;
  language: string | null;
  description: string | null;
  status: string;
  phase: string;
  /** True only when the stored code is the approved code (derived, #59). */
  approved: boolean;
  /** SHA-256 of the stored code; null before any code exists. */
  code_sha256?: string | null;
  /** SHA-256 of the version the user approved; null if none ever was. */
  approved_code_sha256?: string | null;
  detected_secrets: string[];
  created_at: string;
  updated_at: string;
  /** Absent from a gateway older than Feature 006. */
  state?: BuildState;
  state_label?: string;
  state_reason?: string | null;
  steps?: BuildStep[];
  tool_count?: number | null;
  tests_passed?: number | null;
  tests_total?: number | null;
  thread_id?: string | null;
}

export interface BuiltServerList {
  servers: BuiltServer[];
  total: number;
}

export interface StartBuildResponse {
  server_id: string;
  thread_id: string;
  name: string;
  /** The names a secret in the description was stored under. Never values. */
  secret_placeholders: string[];
}

/** GET /api/mcp-studio/servers/{id}/approval (#59). */
export interface ApprovalPacket {
  server_id: string;
  name: string;
  code_sha256: string;
  source_code: string;
  egress_hosts: string[];
  tools: { name: string; description: string; proposed_tier: number }[];
  secret_names: string[];
  view_token: string;
  expires_in_seconds: number;
  /** An approved version is still running while this new code waits. */
  approved_version_on: boolean;
}
