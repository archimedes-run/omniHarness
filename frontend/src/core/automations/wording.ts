/**
 * How the Automations panel words a rule (Feature 006, Automations.dc.html):
 * its schedule ("Weekdays 8:45 AM"), its next run ("Tomorrow 8:45 AM"), its
 * quiet hours ("10 PM to 7 AM") and each run ("Held, then delivered").
 *
 * Times are shown in the RULE's zone, the zone the engine fires it in, so
 * "8:45 AM" means what the rule says wherever the browser is. The next run is
 * the server's (computed with the scheduler's own function); nothing here
 * computes a run time, it only says one.
 */
import type {
  NextRun,
  QuietHoursView,
  RuleView,
  RunView,
} from "@/core/triggers/types";

import { DAY_NAMES, fromCron, matchText } from "./schedule";

const WEEKDAYS = "1,2,3,4,5";
const FULL_DAYS = [
  "Sunday",
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
];

/** "8:45 AM" from "08:45". */
export function clock(hhmm: string): string {
  const [h = 0, m = 0] = hhmm.split(":").map(Number);
  const suffix = h < 12 ? "AM" : "PM";
  const hour = h % 12 === 0 ? 12 : h % 12;
  return `${hour}:${String(m).padStart(2, "0")} ${suffix}`;
}

/** "10 PM" style, for quiet hours: whole hours drop the minutes. */
function shortClock(hhmm: string): string {
  const full = clock(hhmm);
  return full.replace(":00 ", " ");
}

function daysPhrase(days: number[]): string {
  const d = days.join();
  if (days.length === 7) return "Every day";
  if (d === WEEKDAYS) return "Weekdays";
  if (d === "0,6") return "Weekends";
  if (days.length === 1) return `${FULL_DAYS[days[0]!]}s`;
  return days.map((day) => DAY_NAMES[day]).join(", ");
}

const WATCHER_EVENTS: Record<string, string> = {
  "waiting-on-user": "When a session waits on you",
  "session-failed": "When a session fails",
  idle: "When a session finishes or goes quiet",
};

export function watcherPhrase(event: string): string {
  return WATCHER_EVENTS[event] ?? `When the watcher reports “${event}”`;
}

/** The list row's second line: "Weekdays 8:45 AM", "When a session waits on you". */
export function shortSchedule(rule: Pick<RuleView, "type" | "match">): string {
  if (rule.type === "cron") {
    const expr = matchText(rule.match.schedule);
    const simple = fromCron(expr);
    if (!simple) return `Cron ${expr}`;
    return `${daysPhrase(simple.days)} ${clock(simple.time)}`;
  }
  if (rule.type === "watcher")
    return watcherPhrase(matchText(rule.match.event));
  return rule.type;
}

const DESTINATIONS: Record<string, string> = {
  auto: "automatically (Telegram when you're away)",
  remote: "to Telegram",
  quiet: "to Home, quietly",
  local: "on this machine",
};

export function destinationPhrase(destination: string): string {
  return DESTINATIONS[destination] ?? `to ${destination}`;
}

/** The header line: "Weekdays at 8:45 AM · America/New_York · to Telegram". */
export function headline(
  rule: Pick<RuleView, "type" | "match" | "destination" | "timezone">,
): string {
  const parts: string[] = [];
  if (rule.type === "cron") {
    const expr = matchText(rule.match.schedule);
    const simple = fromCron(expr);
    parts.push(
      simple
        ? `${daysPhrase(simple.days)} at ${clock(simple.time)}`
        : `Cron ${expr}`,
    );
    parts.push(ruleZone(rule));
  } else {
    parts.push(shortSchedule(rule));
  }
  parts.push(destinationPhrase(rule.destination));
  return parts.join(" · ");
}

/** The calendar date ("2026-10-21") of an instant in a zone. */
function dateIn(instant: Date, zone: string): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: zone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(instant);
}

function daysBetween(a: string, b: string): number {
  return Math.round(
    (Date.parse(`${b}T00:00:00Z`) - Date.parse(`${a}T00:00:00Z`)) / 86_400_000,
  );
}

/**
 * "Today 8:45 AM", "Tomorrow 8:45 AM", "Fri 8:45 AM" (within the week either
 * way), else "Oct 30, 8:45 AM", in `zone`.
 */
export function when(
  iso: string,
  zone: string,
  now: Date = new Date(),
): string {
  const instant = new Date(iso);
  if (Number.isNaN(instant.getTime())) return "Can't tell yet";
  const tz = zone || "UTC";
  const time = new Intl.DateTimeFormat("en-US", {
    timeZone: tz,
    hour: "numeric",
    minute: "2-digit",
  }).format(instant);
  const gap = daysBetween(dateIn(now, tz), dateIn(instant, tz));
  if (gap === 0) return `Today ${time}`;
  if (gap === 1) return `Tomorrow ${time}`;
  if (gap === -1) return `Yesterday ${time}`;
  if (Math.abs(gap) < 7) {
    const day = new Intl.DateTimeFormat("en-US", {
      timeZone: tz,
      weekday: "short",
    }).format(instant);
    return `${day} ${time}`;
  }
  const date = new Intl.DateTimeFormat("en-US", {
    timeZone: tz,
    month: "short",
    day: "numeric",
  }).format(instant);
  return `${date}, ${time}`;
}

/** Only the clock time, in `zone` ("9:02 AM"). */
export function timeOnly(iso: string, zone: string): string {
  const instant = new Date(iso);
  if (Number.isNaN(instant.getTime())) return "an unrecorded time";
  return new Intl.DateTimeFormat("en-US", {
    timeZone: zone || "UTC",
    hour: "numeric",
    minute: "2-digit",
  }).format(instant);
}

/** The zone a rule's times are shown in: its own, else the user's. */
export function ruleZone(rule: Pick<RuleView, "timezone" | "match">): string {
  return (
    matchText(rule.match.timezone) || (rule.timezone ?? "America/New_York")
  );
}

/** The Next run card. Each non-time state says why there is no time. When
 * the run falls in quiet hours (and is not urgent) it says when it will
 * actually be delivered, and that it was held. */
export function nextRunText(
  rule: Pick<
    RuleView,
    | "next_run"
    | "next_run_at"
    | "deliver_at"
    | "held_for_quiet_hours"
    | "match"
    | "timezone"
  >,
  now: Date = new Date(),
): string {
  const state: NextRun = rule.next_run ?? "cant-tell";
  const zone = ruleZone(rule);
  switch (state) {
    case "scheduled":
      if (!rule.next_run_at) return "Can't tell yet";
      if (rule.held_for_quiet_hours && rule.deliver_at)
        return `${when(rule.deliver_at, zone, now)} (due ${timeOnly(rule.next_run_at, zone)}, held for quiet hours)`;
      return when(rule.next_run_at, zone, now);
    case "off":
      return "None: it is off";
    case "engine-off":
      return "None: the trigger engine is off";
    case "on-event":
      return "When it happens";
    default:
      return "Can't tell yet";
  }
}

export function quietHoursText(
  quiet: QuietHoursView | null | undefined,
  ruleZone?: string,
): string {
  if (!quiet) return "Can't tell yet";
  if (!quiet.enabled) return "Off";
  const span = `${shortClock(quiet.start)} to ${shortClock(quiet.end)}`;
  return ruleZone && ruleZone !== quiet.timezone
    ? `${span} (${quiet.timezone})`
    : span;
}

/** A run's status words and the sentence after them, as on the board. */
export interface RunWords {
  label: string;
  tone: "good" | "info" | "bad" | "muted";
  detail: string;
}

export function runWords(
  run: RunView,
  zone: string,
  nameOf: (ruleId: string) => string = (id) => id,
): RunWords {
  switch (run.kind) {
    case "delivered":
      return {
        label: "Delivered",
        tone: "good",
        detail: run.batch_not_recorded
          ? " (whether it went with others was not recorded)"
          : "",
      };
    case "held-then-delivered": {
      const why =
        run.held_because === "mid-conversation"
          ? " You were mid-conversation."
          : run.held_because === "quiet-hours"
            ? " It was quiet hours."
            : run.held_reason
              ? ` Held because: ${run.held_reason}.`
              : "";
      return {
        label: "Held, then delivered",
        tone: "info",
        detail: ` at ${timeOnly(run.settled_at, zone)}.${why}`,
      };
    }
    case "delivered-with-others": {
      const n = run.delivered_with.length;
      const names = [...new Set(run.delivered_with.map((m) => m.rule_id))]
        .map(nameOf)
        .join(", ");
      return {
        label: `Delivered with ${n} ${n === 1 ? "other" : "others"}`,
        tone: "info",
        detail: ` (${names}), one message`,
      };
    }
    case "failed":
      return {
        label: "Failed",
        tone: "bad",
        detail: run.reason ? `: ${run.reason}` : ": no reason was recorded",
      };
    case "pending":
      return {
        label: "Can't tell yet",
        tone: "muted",
        detail:
          run.held_because === "mid-conversation"
            ? ": held while you are mid-conversation, not delivered yet"
            : run.held_because === "quiet-hours"
              ? ": held for quiet hours, not delivered yet"
              : run.reason
                ? `: not delivered yet (${run.reason})`
                : ": not delivered yet",
      };
    default:
      return {
        label: "Can't tell yet",
        tone: "muted",
        detail: ": the record does not say how it ended",
      };
  }
}

/** A rule's name for people: what they called it, else its id. */
export function ruleName(rule: Pick<RuleView, "id" | "name">): string {
  const name = rule.name?.trim();
  if (name) return name;
  return rule.id;
}

/** A free rule id from a name: "Standup nudge" → "standup-nudge". */
export function idFromName(name: string, taken: Iterable<string>): string {
  const base =
    name
      .toLowerCase()
      .normalize("NFKD")
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 48) || "automation";
  const used = new Set(taken);
  let id = base;
  for (let n = 2; used.has(id); n++) id = `${base}-${n}`;
  return id;
}
