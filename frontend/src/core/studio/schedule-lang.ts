/**
 * Schedules in words, and their next runs (006-G Studio, Schedule step).
 *
 * The editor holds a preset (every day / weekdays / weekly on some days / a
 * custom cron), a time and an IANA zone; it writes a five-field cron, the only
 * shape the 006-F schedule routes accept. Next runs are computed in the
 * SCHEDULE's zone (the engine evaluates them there) and shown as instants in
 * the viewer's zone.
 */

import { fromCron, toCron, type Day } from "@/core/automations/schedule";

export type SchedulePreset = "daily" | "weekdays" | "weekly" | "custom";

export interface ScheduleEdit {
  preset: SchedulePreset;
  /** "HH:MM", 24-hour. */
  time: string;
  /** Weekly only: 0 = Sunday ... 6 = Saturday. */
  days: Day[];
  /** Custom only: the raw expression. */
  cron: string;
  timezone: string;
}

export const WEEK: Day[] = [1, 2, 3, 4, 5, 6, 0];
const WEEKDAYS = "1,2,3,4,5";
export const DAY_SHORT = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const DAY_LONG = [
  "Sunday",
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
];

/** The editor's state for a stored cron: never rewrites what it cannot show. */
export function editOf(cron: string, timezone: string): ScheduleEdit {
  const simple = fromCron(cron);
  if (!simple)
    return { preset: "custom", time: "09:00", days: [1], cron, timezone };
  const key = simple.days.join();
  const preset: SchedulePreset =
    simple.days.length === 7
      ? "daily"
      : key === WEEKDAYS
        ? "weekdays"
        : "weekly";
  return {
    preset,
    time: simple.time,
    days: preset === "weekly" ? simple.days : [1],
    cron,
    timezone,
  };
}

/** The cron the editor's state means; "" when it means nothing yet. */
export function cronOf(edit: ScheduleEdit): string {
  if (edit.preset === "custom") return edit.cron.trim();
  if (!/^\d{2}:\d{2}$/.test(edit.time)) return "";
  const days: Day[] =
    edit.preset === "daily"
      ? [0, 1, 2, 3, 4, 5, 6]
      : edit.preset === "weekdays"
        ? [1, 2, 3, 4, 5]
        : edit.days;
  if (days.length === 0) return "";
  return toCron({ time: edit.time, days });
}

/** "6:30 PM" from "18:30". */
export function clock12(hhmm: string): string {
  const [h = 0, m = 0] = hhmm.split(":").map(Number);
  const ap = h >= 12 ? "PM" : "AM";
  return `${h % 12 || 12}:${String(m).padStart(2, "0")} ${ap}`;
}

/** The zone's short name at `at` ("EDT"), or the zone itself. */
export function zoneAbbr(zone: string, at: Date = new Date()): string {
  try {
    const part = new Intl.DateTimeFormat("en-US", {
      timeZone: zone,
      timeZoneName: "short",
    })
      .formatToParts(at)
      .find((p) => p.type === "timeZoneName")?.value;
    return part && !/^GMT[+-]/.test(part) ? part : zone.replace(/_/g, " ");
  } catch {
    return zone;
  }
}

function andList(items: string[]): string {
  if (items.length <= 1) return items.join("");
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

/** "Every weekday at 6:30 PM EDT"; a cron it cannot word stays a cron. */
export function recurrenceText(cron: string, timezone: string): string {
  const simple = fromCron(cron);
  const tz = zoneAbbr(timezone);
  if (!simple)
    return cron.trim()
      ? `Custom schedule (${cron.trim()}, ${tz})`
      : "Custom schedule";
  const at = `at ${clock12(simple.time)} ${tz}`;
  const key = simple.days.join();
  if (simple.days.length === 7) return `Every day ${at}`;
  if (key === WEEKDAYS) return `Every weekday ${at}`;
  if (key === "0,6") return `Every weekend ${at}`;
  if (simple.days.length === 1)
    return `Every ${DAY_LONG[simple.days[0]!]} ${at}`;
  const ordered = WEEK.filter((d) => simple.days.includes(d));
  return `Every ${andList(ordered.map((d) => DAY_SHORT[d]!))} ${at}`;
}

function offsetMinutes(zone: string, at: Date): number {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: zone,
    hourCycle: "h23",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).formatToParts(at);
  const get = (type: string) =>
    Number(parts.find((p) => p.type === type)?.value ?? 0);
  const asUtc = Date.UTC(
    get("year"),
    get("month") - 1,
    get("day"),
    get("hour") % 24,
    get("minute"),
    get("second"),
  );
  return Math.round((asUtc - at.getTime()) / 60000);
}

/** The instant a wall-clock time in `zone` names. */
export function zonedInstant(
  year: number,
  month: number,
  day: number,
  hour: number,
  minute: number,
  zone: string,
): Date {
  const guess = Date.UTC(year, month, day, hour, minute);
  const first = offsetMinutes(zone, new Date(guess));
  let at = guess - first * 60000;
  const second = offsetMinutes(zone, new Date(at));
  if (second !== first) at = guess - second * 60000;
  return new Date(at);
}

/** The next `n` runs of a simple cron in its zone (custom shapes: none, the
 * server's next run is shown instead). */
export function nextRuns(
  cron: string,
  timezone: string,
  now: Date = new Date(),
  n = 3,
): Date[] {
  const simple = fromCron(cron);
  if (!simple) return [];
  let zone = timezone;
  try {
    new Intl.DateTimeFormat("en-US", { timeZone: zone });
  } catch {
    zone = "UTC";
  }
  const [h = 0, m = 0] = simple.time.split(":").map(Number);
  const today = new Intl.DateTimeFormat("en-CA", {
    timeZone: zone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  })
    .format(now)
    .split("-")
    .map(Number);
  const [y = 1970, mo = 1, d = 1] = today;
  const out: Date[] = [];
  for (let i = 0; i < 21 && out.length < n; i++) {
    const date = new Date(Date.UTC(y, mo - 1, d + i));
    const weekday = date.getUTCDay() as Day;
    if (!simple.days.includes(weekday)) continue;
    const at = zonedInstant(
      date.getUTCFullYear(),
      date.getUTCMonth(),
      date.getUTCDate(),
      h,
      m,
      zone,
    );
    if (at > now) out.push(at);
  }
  return out;
}

function dayDiff(at: Date, now: Date): number {
  const start = (x: Date) =>
    new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  return Math.round((start(at) - start(now)) / 86_400_000);
}

/** "Today 6:30 PM", "Tomorrow 9:00 AM", "Mon Oct 26, 8:30 AM" (viewer's zone). */
export function runText(at: Date, now: Date = new Date()): string {
  const time = at.toLocaleTimeString("en-US", {
    hour: "numeric",
    minute: "2-digit",
  });
  const diff = dayDiff(at, now);
  if (diff === 0) return `Today ${time}`;
  if (diff === 1) return `Tomorrow ${time}`;
  const day = at.toLocaleDateString("en-US", { weekday: "short" });
  const date = at.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
  return `${day} ${date}, ${time}`;
}

/** The list's shorter form: "Today, 6:00 PM", "Mon, 8:45 AM", "Oct 30, 9:00 AM". */
export function runShort(at: Date, now: Date = new Date()): string {
  const time = at.toLocaleTimeString("en-US", {
    hour: "numeric",
    minute: "2-digit",
  });
  const diff = dayDiff(at, now);
  if (diff === 0) return `Today, ${time}`;
  if (diff === 1) return `Tomorrow, ${time}`;
  if (diff > 1 && diff < 7)
    return `${at.toLocaleDateString("en-US", { weekday: "short" })}, ${time}`;
  return `${at.toLocaleDateString("en-US", { month: "short", day: "numeric" })}, ${time}`;
}
