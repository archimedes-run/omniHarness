/** Pure helpers, kept out of the components so they can be tested without a
 *  browser. The countdown and the threshold rule are the two places a bug
 *  would be invisible in review and obvious to a user. */

import type { PendingAction } from "./types";

/** Milliseconds until expiry; negative once it has passed. */
export function msRemaining(expiresAt: string, now: Date): number {
  return new Date(expiresAt).getTime() - now.getTime();
}

/** FR-005. An action that expires while displayed becomes expired WITHOUT a
 *  reload, so this is computed from the clock rather than from the fetch. */
export function isExpired(action: PendingAction, now: Date): boolean {
  return msRemaining(action.expires_at, now) <= 0;
}

export function formatRemaining(expiresAt: string, now: Date): string {
  const ms = msRemaining(expiresAt, now);
  if (ms <= 0) return "expired";
  const totalMinutes = Math.floor(ms / 60_000);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  if (hours > 0) return `${hours}h ${minutes}m left`;
  if (totalMinutes > 0) return `${totalMinutes}m left`;
  return `${Math.floor(ms / 1000)}s left`;
}

/** The card's clock, in the board's words: "Expires in 3h 58m", or "Expired". */
export function formatExpiresIn(expiresAt: string, now: Date): string {
  const left = formatRemaining(expiresAt, now);
  if (left === "expired") return "Expired";
  return `Expires in ${left.replace(/ left$/, "")}`;
}

/** FR-009. Above the threshold a click is not enough; the user supplies the
 *  target count, which they can only produce by having read what they are
 *  approving. */
export function requiresTypedCount(action: PendingAction): boolean {
  return action.targets.length > action.threshold_targets;
}

/** Whether Confirm may be pressed at all.
 *
 *  DECLINING IS NEVER BLOCKED BY THE THRESHOLD — proof of reading is required
 *  to ACT, not to refuse. Making a decline harder than a confirmation would
 *  push a hesitant user toward the dangerous answer. */
export function canConfirm(
  action: PendingAction,
  typed: string,
  now: Date,
): boolean {
  if (isExpired(action, now)) return false;
  if (!requiresTypedCount(action)) return true;
  return typed.trim() === String(action.targets.length);
}

export function canDecline(action: PendingAction, now: Date): boolean {
  return !isExpired(action, now);
}

/** FR-006: what suggested an action the user did not ask for, or null when it
 *  was their own request. The backend sends the sentence; the fallback covers
 *  a response that names the origin without it. */
export function originLabel(action: PendingAction): string | null {
  if (!action.origin || action.origin === "user") return null;
  if (action.origin_label) return action.origin_label;
  if (action.origin === "automation") return "Suggested by an automation";
  if (action.origin === "content") {
    const source = action.origin_source?.trim();
    return `Suggested by content from ${source && source.length > 0 ? source : "a tool result"}`;
  }
  return "I could not tell what suggested this";
}
