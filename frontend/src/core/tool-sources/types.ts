/** Mirrors app/gateway/tool_sources.py. */
export type LocalState =
  | "not-configured"
  | "disabled"
  | "unreachable"
  | "live"
  | "not-loaded";
export type ConnectorState =
  | "not-authorised"
  | "authorised"
  | "authorised-selected"
  | "authorised-not-selected";

export interface ToolSource {
  id: string;
  name: string;
  kind: "local" | "connector";
  state: LocalState | ConnectorState;
  tool_count: number | null;
  error: string | null;
  selected: boolean | null;
  /** Feature 006: when a call to this source last came back without error
   * (observed working), and when one last failed. Absent from an older
   * gateway; null when never seen. */
  last_success_at?: string | null;
  last_failure_at?: string | null;
  last_error?: string | null;
  last_error_withheld?: boolean;
}

export interface ToolSourcesView {
  sources: ToolSource[];
  failing: number;
  thread_id: string | null;
  connectors_available: boolean;
}
