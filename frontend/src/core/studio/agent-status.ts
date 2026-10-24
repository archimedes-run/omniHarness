/**
 * An agent's status pill and next-run line on the Agents list (006-G, owner
 * decision 1), read from what the trigger engine reports for it.
 *
 *   Draft      no instructions yet: it cannot do much until it has some
 *   On demand  no schedule: it works only when you chat with it
 *   Paused     it has schedules and every one is switched off
 *   Scheduled  at least one schedule is on, and it has not run yet
 *   Active     at least one schedule is on, and it has run
 */

import { runShort } from "./schedule-lang";
import type { AgentRuns } from "./types";

export type AgentStatus =
  | "active"
  | "scheduled"
  | "draft"
  | "ondemand"
  | "paused";

export const STATUS_ORDER: AgentStatus[] = [
  "active",
  "scheduled",
  "draft",
  "ondemand",
  "paused",
];

/** null while its schedules are not known yet. */
export function agentStatus(
  soul: string | null | undefined,
  runs: AgentRuns | undefined,
): AgentStatus | null {
  if (!soul?.trim()) return "draft";
  if (!runs) return null;
  const schedules = runs.schedules;
  if (schedules.length === 0) return "ondemand";
  if (!schedules.some((s) => s.enabled)) return "paused";
  return runs.recent.length > 0 ? "active" : "scheduled";
}

/** The soonest run of its switched-on schedules, or null. */
export function nextRunAt(runs: AgentRuns | undefined): Date | null {
  const times = (runs?.schedules ?? [])
    .filter((s) => s.enabled && s.next_run)
    .map((s) => new Date(s.held_until ?? s.next_run!))
    .filter((d) => !Number.isNaN(d.getTime()))
    .sort((a, b) => a.getTime() - b.getTime());
  return times[0] ?? null;
}

/** The card's clock line. */
export function nextRunLine(
  status: AgentStatus | null,
  runs: AgentRuns | undefined,
  now: Date = new Date(),
): string {
  if (status === null) return "…";
  if (status === "draft") return "Not scheduled";
  if (status === "ondemand") return "When you ask";
  if (status === "paused") return "Paused";
  const next = nextRunAt(runs);
  if (!next) return "No upcoming run";
  const when = runShort(next, now);
  return status === "scheduled" ? `First run ${when}` : when;
}
