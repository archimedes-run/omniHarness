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
  /** In quiet hours and not urgent: its message is held until then. */
  held_until?: string | null;
}

export interface CalendarEvent {
  title: string;
  /** A time with its offset, or a date ("2026-10-23") for all day. */
  start: string;
  all_day: boolean;
}

/** Google Calendar, read through the existing connection. */
export interface CalendarView {
  state: "ok" | "not-set-up" | "unavailable";
  detail: string | null;
  events: CalendarEvent[];
}

export interface UpcomingView {
  /** False: automations are off, so nothing is scheduled. */
  engine_enabled: boolean;
  /** Set when the rule file could not be read: runs may be missing. */
  rules_error: string | null;
  runs: UpcomingRun[];
  calendar: CalendarView;
}

export type SourceState = "ok" | "unavailable" | "off" | "not-set-up";

export interface MovedItem {
  at: string;
  source: "ledger" | "automation" | "session" | "github";
  text: string;
  /** Who made the change, in words. */
  by: string | null;
  project_id: string | null;
  thread_id: string | null;
  /** How it is known, said in words on the row. */
  known: "observed" | "reported" | "inferred";
  url: string | null;
}

export interface MovedView {
  items: MovedItem[];
  sources: {
    ledger: SourceState;
    automations: SourceState;
    sessions?: SourceState;
    github?: SourceState;
  };
}
