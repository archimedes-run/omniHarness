/** The eight outcomes the backend can return. Never collapsed into ok/error:
 *  "someone else already confirmed it", "it expired" and "the items changed"
 *  each need a different response from the person reading them, and a generic
 *  failure tells them to retry something that will never work. */
export type ResolveOutcome =
  | "executed"
  | "declined"
  | "already_resolved"
  | "expired"
  | "targets_drifted"
  | "unrecognised"
  | "threshold_not_met"
  | "failed";

export interface PendingAction {
  id: string;
  tool_name: string;
  plan_text: string;
  targets: string[];
  requester: string;
  delegation_chain: string[];
  expires_at: string;
  thread_id: string | null;
  threshold_targets: number;
  requires_typed_count: boolean;
}

export interface PendingList {
  actions: PendingAction[];
  /** FR-008. `false` means we could not tell what is pending — a different
   *  fact from nothing being pending, and the surface must not render the
   *  same thing for both. */
  readable: boolean;
  error: string;
}

export interface ResolveResult {
  outcome: ResolveOutcome;
  action_id: string | null;
  message: string;
  detail: Record<string, unknown>;
}
