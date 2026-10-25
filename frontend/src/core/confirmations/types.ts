/** The outcomes the backend can return. Never collapsed into ok/error:
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
  | "failed"
  /** The tool is not available in this chat now (its source was removed or
   *  is disconnected, or the agent that asked was removed or deleted).
   *  Nothing ran; the card stays. */
  | "tool_unavailable"
  /** The chat is mid-reply, and this result is posted into it. Nothing ran;
   *  confirm again when the reply has finished. */
  | "thread_busy"
  /** Too many confirmed calls are running; nothing ran, confirm again later. */
  | "confirm_busy"
  /** A decline that arrived while the confirmed call was running: it cannot
   *  stop it, and the result is shown when it finishes. */
  | "already_running"
  /** The chat this was proposed in was deleted: refused, nothing ran. */
  | "chat_deleted"
  /** A typed "yes" in chat for an action the user did not cause: only the
   *  card's button can confirm it. Never returned by the card's own route. */
  | "card_only"
  /** An edited plan that could not be applied: nothing ran, the original
   *  plan is still open, and the edit can be corrected and saved again. */
  | "invalid_plan";

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
  /** Failed redaction: the text fields carry a sentence saying so (FR-031). */
  withheld: boolean;
  /** The call's arguments, only for tools whose plan can be edited before
   *  confirming (ledger_apply). Absent otherwise. */
  arguments?: Record<string, unknown> | null;
  /** Every call's arguments for display, each value as text that passed
   *  redaction (a value that failed reads "Withheld"). Absent from a gateway
   *  that does not send it: the card then shows the targets as stated. */
  arguments_display?: Record<string, string> | null;
  /** What caused the proposal. Anything but "user" (content the assistant
   *  read, an automation, or a cause nobody could tell) can only be confirmed
   *  with this card's button. Optional: an older backend omits them. */
  origin?: "user" | "content" | "automation" | "unknown";
  /** For "content": the tool(s) whose output suggested it. */
  origin_source?: string;
  /** The sentence to show, e.g. "Suggested by content from web_fetch". */
  origin_label?: string;
  /** For a subagent's request: the agent the content reached it through. */
  origin_via?: string;
  confirmable_by_typing?: boolean;
  /** A routine ledger write waiting as a suggestion: it can be applied with
   *  others in one undoable batch ("Apply all"). Never true for Tier 3. */
  suggestion?: boolean;
  /** An outbound call (web_search, web_fetch, image_search) the lead asked
   *  about because its turn had read private data. Such cards from one turn
   *  share `group` and are shown as ONE card with "Apply all". */
  outbound?: boolean;
  /** The turn the card was stated in (opaque); "" when it has no group. */
  group?: string;
}

/** A confirmed action that ran, whose result is not yet in its chat (the
 *  chat was replying, or the gateway restarted first). It is posted once the
 *  chat is free. */
export interface AwaitingPost {
  id: string;
  thread_id: string | null;
  tool_name: string;
  requester: string;
  /** "waiting" (it will be posted), "failed" (retries ran out) or "dropped"
   *  (the chat was deleted). Absent from an older gateway: "waiting". */
  post_state?: "waiting" | "failed" | "dropped";
  /** For "failed" and "dropped": the result, kept here. */
  result?: string;
}

export interface PendingList {
  actions: PendingAction[];
  /** Absent from an older gateway. */
  awaiting_post?: AwaitingPost[];
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
