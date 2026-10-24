/** Mirrors app/gateway/triggers_view.py. */
export type Activity = "never-evaluated" | "evaluated-never-fired" | "fired";
export type Recorded = "recorded" | "never" | "not-recorded";
export type Outcome =
  | "delivered"
  | "suppressed"
  | "queued"
  | "expired"
  | "failed";

/** When a rule next runs, as the server computed it (never a guess). */
export type NextRun =
  | "scheduled"
  | "off"
  | "engine-off"
  | "on-event"
  | "cant-tell";

export interface RuleView {
  id: string;
  /** The display name the person gave it; "" for a rule written without one. */
  name?: string;
  type: string;
  enabled: boolean;
  match: Record<string, unknown>;
  prompt: string;
  destination: string;
  urgent: boolean;
  activity: Activity;
  last_evaluated_at: string | null;
  last_evaluated: Recorded;
  last_fired_at: string | null;
  last_outcome: Outcome | null;
  next_run?: NextRun;
  /** ISO instant with the rule zone's offset, when next_run is "scheduled". */
  next_run_at?: string | null;
  /** When that run is delivered: quiet hours' end if it fires inside them. */
  deliver_at?: string | null;
  held_for_quiet_hours?: boolean;
  /** Zone to show its times in: the rule's own, else the user's. */
  timezone?: string;
  /** Feature 006-F: the custom agent it runs as; null is the lead. */
  agent?: string | null;
  /** Feature 006-F: whether Home shows its upcoming runs and results. */
  show_on_home?: boolean;
}

export interface QuietHoursView {
  enabled: boolean;
  start: string;
  end: string;
  timezone: string;
}

export interface RulesView {
  engine_enabled: boolean;
  rules: RuleView[];
  rules_error: string | null;
  /** Hash of the rule file; an edit names it, and is refused if stale. */
  version: string | null;
  writable: boolean;
  not_writable_reason: string | null;
  /** The rule file's quiet hours; null when the file could not be read. */
  quiet_hours?: QuietHoursView | null;
}

export interface FiringView {
  at: string;
  rule_id: string;
  event_type: string;
  event_id: string;
  outcome: Outcome;
  /** Verbatim from the audit log (FR-019). */
  reason: string;
  batch: "alone" | "batched" | "not-recorded";
  batch_id: string | null;
  delivered_with: { rule_id: string; event_id: string }[];
  thread_id?: string | null;
}

/** One run of one rule, worded from its audit records (triggers_view.py). */
export type RunKind =
  | "delivered"
  | "held-then-delivered"
  | "delivered-with-others"
  | "failed"
  | "pending"
  | "cant-tell";

export interface RunView {
  event_id: string;
  /** When it was due (cron) or first recorded. */
  at: string;
  kind: RunKind;
  settled_at: string;
  /** The final record's reason, verbatim. */
  reason: string;
  held_because: "mid-conversation" | "quiet-hours" | "other" | null;
  held_reason: string;
  delivered_with: { rule_id: string; event_id: string }[];
  batch_not_recorded: boolean;
  thread_id: string | null;
  /** The run's full content in the run history, when stored. */
  run_id?: string | null;
  content?: "stored" | "not-stored" | "unavailable";
}

export interface RunsView {
  rule_id: string;
  runs: RunView[];
}

export interface FiringsView {
  firings: FiringView[];
}
