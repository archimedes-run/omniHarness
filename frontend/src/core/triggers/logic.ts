import type { Activity, Outcome, Recorded } from "./types";

/** FR-017: three conditions that used to look identical. */
export const ACTIVITY_LABEL: Record<Activity, string> = {
  "never-evaluated": "Never evaluated",
  "evaluated-never-fired": "Evaluating, never fired",
  fired: "Has fired",
};

/** FR-018: every outcome distinguishable, by label and by icon. */
export const OUTCOME_LABEL: Record<Outcome, string> = {
  delivered: "Delivered",
  suppressed: "Suppressed",
  queued: "Held",
  expired: "Expired",
  failed: "Failed",
};

/**
 * FR-022. A missing timestamp is one of two different facts: it never
 * happened, or it was not recorded (the record predates the field). Neither
 * is rendered as a blank.
 */
export function timestamp(value: string | null, recorded: Recorded): string {
  if (value) return new Date(value).toLocaleString();
  return recorded === "not-recorded" ? "not recorded" : "never";
}
