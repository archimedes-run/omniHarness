/** Mirrors app/gateway/inbox_view.py. */
export type AlertState =
  | "waiting"
  | "not-delivered"
  | "suppressed"
  | "delivered";

export interface Alert {
  rule_id: string;
  event_id: string;
  event_type: string;
  at: string;
  state: AlertState;
  /** Verbatim from the audit record. */
  reason: string;
  /** The rule's conversation, where the message and any reply live. */
  thread_id: string | null;
}

export interface InboxAlerts {
  alerts: Alert[];
  /** Waiting plus not-delivered: what counts toward the badge. */
  waiting_count: number;
}
