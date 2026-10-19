/** Mirrors app/gateway/triggers_view.py. */
export type Activity = "never-evaluated" | "evaluated-never-fired" | "fired";
export type Recorded = "recorded" | "never" | "not-recorded";
export type Outcome =
  | "delivered"
  | "suppressed"
  | "queued"
  | "expired"
  | "failed";

export interface RuleView {
  id: string;
  type: string;
  enabled: boolean;
  match: Record<string, unknown>;
  activity: Activity;
  last_evaluated_at: string | null;
  last_evaluated: Recorded;
  last_fired_at: string | null;
  last_outcome: Outcome | null;
}

export interface RulesView {
  engine_enabled: boolean;
  rules: RuleView[];
  rules_error: string | null;
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
}

export interface FiringsView {
  firings: FiringView[];
}
