/** Mirrors app/gateway/routers/home.py and app/gateway/home_view.py. */
export interface HomeDismissals {
  /** "<rule_id>:<event_id>" of each alert dismissed on Home. */
  alert_keys: string[];
  /** "Not now" on the name prompt: it is asked once. */
  name_prompt_dismissed: boolean;
}

export interface UpcomingRun {
  rule_id: string;
  title: string;
  prompt: string;
  /** ISO, with its offset. */
  at: string;
  schedule: string;
  timezone: string | null;
}

export interface UpcomingView {
  /** False: automations are off, so nothing is scheduled. */
  engine_enabled: boolean;
  /** Set when the rule file could not be read: runs may be missing. */
  rules_error: string | null;
  runs: UpcomingRun[];
  calendar: "not-set-up";
}

export type SourceState = "ok" | "unavailable" | "off";

export interface MovedItem {
  at: string;
  source: "ledger" | "automation";
  text: string;
  /** Who made the change, in words. */
  by: string | null;
  project_id: string | null;
  thread_id: string | null;
}

export interface MovedView {
  items: MovedItem[];
  sources: { ledger: SourceState; automations: SourceState };
}
