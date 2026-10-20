/**
 * Pure helpers for Home (Feature 006, Main board), kept out of the components
 * so the wording and the arithmetic are unit-tested.
 */
import type { Alert } from "@/core/inbox/types";
import type { DisplayState, SessionRow } from "@/core/sessions/types";

/** The one key a dismissal names an alert by (the gateway uses the same). */
export const alertKey = (a: Pick<Alert, "rule_id" | "event_id">) =>
  `${a.rule_id}:${a.event_id}`;

/** "Good morning" 5:00–11:59, "Good afternoon" 12:00–16:59, else evening. */
export function greeting(now: Date, name?: string | null): string {
  const hour = now.getHours();
  const part =
    hour >= 5 && hour < 12
      ? "Good morning"
      : hour >= 12 && hour < 17
        ? "Good afternoon"
        : "Good evening";
  // No name while it cannot be told: never a placeholder.
  return name?.trim() ? `${part}, ${name.trim()}` : part;
}

/** "Monday, October 19". */
export function dateLine(now: Date): string {
  return now.toLocaleDateString("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
  });
}

/**
 * "2 things need you", from each source's count, or null where a source
 * could not be read. A source that cannot be read never reads as zero.
 */
export function needsYou(counts: (number | null | undefined)[]): string {
  const known = counts.filter((c): c is number => typeof c === "number");
  const total = known.reduce((sum, c) => sum + c, 0);
  const blind = known.length < counts.length;
  const things = (n: number) =>
    `${n} ${n === 1 ? "thing needs" : "things need"} you`;
  if (!blind) return total === 0 ? "Nothing needs you" : things(total);
  if (total === 0) return "Can't tell yet what needs you";
  return `At least ${things(total)}`;
}

/** The local midnight that starts `now`'s day. */
export function startOfDay(now: Date): Date {
  return new Date(now.getFullYear(), now.getMonth(), now.getDate());
}

/** "12s ago", "6 min ago", "3 h ago", "2 d ago"; null for no time. */
export function ago(iso: string | null | undefined, now: Date): string | null {
  if (!iso) return null;
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return null;
  const seconds = Math.max(0, Math.round((now.getTime() - then) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours} h ago`;
  return `${Math.round(hours / 24)} d ago`;
}

/** "Seconds" as an age, the same scale as `ago`. */
export function ageOf(seconds: number | null | undefined): string | null {
  if (seconds == null) return null;
  return ago(new Date(0).toISOString(), new Date(seconds * 1000));
}

const time = (d: Date) =>
  d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });

/** When an upcoming run is, in the viewer's zone: "Today 4:00 PM",
 * "Tomorrow 8:45 AM", "Fri 5:00 PM", or "Oct 30 5:00 PM" beyond a week. */
export function whenLabel(iso: string, now: Date): string {
  const at = new Date(iso);
  const days = Math.round(
    (startOfDay(at).getTime() - startOfDay(now).getTime()) / 86_400_000,
  );
  if (days === 0) return `Today ${time(at)}`;
  if (days === 1) return `Tomorrow ${time(at)}`;
  if (days > 1 && days < 7)
    return `${at.toLocaleDateString("en-US", { weekday: "short" })} ${time(at)}`;
  return `${at.toLocaleDateString("en-US", { month: "short", day: "numeric" })} ${time(at)}`;
}

/** A clock time for today's events: "8:45 AM". */
export const clock = (iso: string) => time(new Date(iso));

/** "Due Fri, Oct 23" for a plain date ("2026-10-23"), read as that local day. */
export function dueLabel(date: string): string {
  const [y, m, d] = date.split("-").map(Number);
  if (!y || !m || !d) return `Due ${date}`;
  const local = new Date(y, m - 1, d);
  return `Due ${local.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" })}`;
}

/** "3 of 7 tasks"; null when the project has no task list yet. */
export function taskProgress(p: { open_tasks: number; done_tasks: number }): {
  label: string;
  percent: number;
} | null {
  const total = p.open_tasks + p.done_tasks;
  if (total === 0) return null;
  return {
    label: `${p.done_tasks} of ${total} task${total === 1 ? "" : "s"}`,
    percent: Math.round((p.done_tasks / total) * 100),
  };
}

export type Tone = "good" | "warn" | "bad" | "muted";

/** Status words as the sessions page says them (STATE_LABEL); a finished one
 * says how long ago. Hedged states stay hedged. */
export function sessionStatus(
  session: Pick<SessionRow, "display_state" | "last_activity_at">,
  label: Record<DisplayState, string>,
  now: Date,
): { text: string; tone: Tone } {
  const state = session.display_state;
  const base = label[state];
  if (state === "completed") {
    const when = ago(session.last_activity_at, now);
    return { text: when ? `${base} ${when}` : base, tone: "muted" };
  }
  const tone: Tone =
    state === "working"
      ? "good"
      : state === "waiting-on-user"
        ? "warn"
        : state === "failed"
          ? "bad"
          : "muted";
  return { text: base, tone };
}

/** How a session's state is known, said in words. */
export function knownBy(epistemic: SessionRow["epistemic"]): string {
  return epistemic === "observed"
    ? "Observed"
    : epistemic === "inferred"
      ? "Inferred"
      : "Can't tell";
}

/** An all-day calendar date ("2026-10-23") as a day: "Today", "Tomorrow",
 * "Fri", or "Oct 30" beyond a week. */
export function dayLabel(date: string, now: Date): string {
  const [y, m, d] = date.split("-").map(Number);
  if (!y || !m || !d) return date;
  const local = new Date(y, m - 1, d);
  const days = Math.round(
    (local.getTime() - startOfDay(now).getTime()) / 86_400_000,
  );
  if (days === 0) return "Today";
  if (days === 1) return "Tomorrow";
  if (days > 1 && days < 7)
    return local.toLocaleDateString("en-US", { weekday: "short" });
  return local.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

/** The instant an upcoming entry sorts by (an all-day date at its local
 * midnight). */
export function sortTime(start: string, allDay: boolean): number {
  if (!allDay) return new Date(start).getTime();
  const [y, m, d] = start.split("-").map(Number);
  return new Date(y ?? 0, (m ?? 1) - 1, d ?? 1).getTime();
}

/** "morning-briefing" -> "Morning briefing": rules have an id, not a name
 * (the gateway's rule_title says the same). */
export function ruleTitle(ruleId: string): string {
  const text = ruleId.split(/[-_]/).filter(Boolean).join(" ");
  return text ? text[0]!.toUpperCase() + text.slice(1) : ruleId;
}
