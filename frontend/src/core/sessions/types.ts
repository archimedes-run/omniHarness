/** Mirrors app/gateway/sessions_view.py. */
export type DisplayState =
  | "working"
  | "waiting-on-user"
  | "completed"
  | "stalled"
  | "failed"
  | "unknown";

export interface SessionRow {
  session_id: string;
  project: string;
  display_state: DisplayState;
  /** How the state is known (FR-011): seen, or inferred from silence. */
  epistemic: "observed" | "inferred" | "unknown";
  last_activity_at: string | null;
  quiet_seconds: number | null;
  summary: string;
  summary_provenance: string;
  relay_suppressed: boolean;
  /** Failed redaction: the text fields carry a sentence saying so (FR-031). */
  withheld: boolean;
}

export interface SessionsView {
  /** Transport: could the gateway ask the watcher at all. */
  reachable: boolean;
  unreachable_kind: "not-configured" | "disabled" | "unreachable" | null;
  unreachable_detail: string | null;
  /** The watcher's own report on its data. Null when it could not be asked. */
  observability: "live" | "stale" | "never-observed" | null;
  staleness_seconds: number | null;
  as_of: string | null;
  /** Null when the watcher could not be asked — never [] for that (SC-006). */
  sessions: SessionRow[] | null;
  /** Set when the watcher did not answer in time and `sessions` is its last
   * answer, this many seconds old. `reachable` is false alongside it. */
  last_known_age_seconds?: number | null;
  observe_only: boolean;
  observe_only_reason: string;
}
