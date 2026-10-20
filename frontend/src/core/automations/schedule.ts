/**
 * A cron schedule as the Automations form edits it: a time, days of the week
 * and a time zone (Phase 2.5).
 *
 * Only the shape "M H * * DAYS" is representable. Anything else (every 15
 * minutes, the 1st of the month) returns null from fromCron, and the form edits
 * the raw expression instead of silently rewriting a schedule it cannot show.
 * The engine validates the result either way.
 */

/** 0 = Sunday ... 6 = Saturday, as cron counts them. */
export type Day = 0 | 1 | 2 | 3 | 4 | 5 | 6;
export const DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const WEEKDAYS: Day[] = [1, 2, 3, 4, 5];
const ALL: Day[] = [0, 1, 2, 3, 4, 5, 6];

export interface SimpleSchedule {
  /** "HH:MM", 24-hour. */
  time: string;
  days: Day[];
}

function parseDays(field: string): Day[] | null {
  if (field === "*") return [...ALL];
  const days = new Set<Day>();
  for (const part of field.split(",")) {
    const range = /^(\d)(?:-(\d))?$/.exec(part);
    if (!range) return null;
    const from = Number(range[1]);
    const to = range[2] != null ? Number(range[2]) : from;
    if (from > 7 || to > 7 || to < from) return null;
    for (let d = from; d <= to; d++) days.add((d % 7) as Day); // 7 is Sunday too
  }
  return [...days].sort((a, b) => a - b);
}

export function fromCron(expr: string): SimpleSchedule | null {
  const fields = expr.trim().split(/\s+/);
  if (fields.length !== 5) return null;
  const [minute, hour, dom, month, dow] = fields as [
    string,
    string,
    string,
    string,
    string,
  ];
  if (!/^\d{1,2}$/.test(minute) || !/^\d{1,2}$/.test(hour)) return null;
  if (dom !== "*" || month !== "*") return null;
  const m = Number(minute);
  const h = Number(hour);
  if (m > 59 || h > 23) return null;
  const days = parseDays(dow);
  if (!days || days.length === 0) return null;
  return {
    time: `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`,
    days,
  };
}

function daysField(days: Day[]): string {
  const sorted = [...new Set(days)].sort((a, b) => a - b);
  if (sorted.length === 7) return "*";
  if (sorted.join() === WEEKDAYS.join()) return "1-5";
  return sorted.join(",");
}

export function toCron({ time, days }: SimpleSchedule): string {
  const [h, m] = time.split(":").map(Number);
  return `${m} ${h} * * ${daysField(days)}`;
}

export function describeSchedule(expr: string, timezone?: string): string {
  const simple = fromCron(expr);
  // A rule naming no zone runs in the engine's default (scheduler.py).
  const zone = ` (${timezone ?? "America/New_York"})`;
  if (!simple) return `Cron "${expr}"${zone}`;
  const d = simple.days.join();
  const when =
    simple.days.length === 7
      ? "Every day"
      : d === WEEKDAYS.join()
        ? "Weekdays"
        : d === "0,6"
          ? "Weekends"
          : simple.days.map((day) => DAY_NAMES[day]).join(", ");
  return `${when} at ${simple.time}${zone}`;
}

/** A rule's match fields are untyped JSON; read one as text, or "". */
export function matchText(value: unknown): string {
  return typeof value === "string" ? value : "";
}
