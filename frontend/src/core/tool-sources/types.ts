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
}

export interface ToolSourcesView {
  sources: ToolSource[];
  failing: number;
  thread_id: string | null;
  connectors_available: boolean;
}
