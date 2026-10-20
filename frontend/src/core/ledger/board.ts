/**
 * How the Tasks panel (Feature 006, Tasks.dc.html) groups and words a
 * project's tasks. Pure, so the grouping and wording are unit tested.
 *
 * The ledger keeps the USER's plan (Feature 005 FR-013): a task's status is
 * what the user (or the assistant on their confirmation) set. Evidence, what
 * was observed (a commit, a session) or reported (an agent's own todo list),
 * is a separate record and never changes the status. These words keep the two
 * apart: a status reads as the plan ("Doing"), never as an observation
 * ("Working").
 */
import type { Owner, Task } from "./types";

export interface TaskGroup {
  key: "progress" | "todo" | "done";
  label: string;
  tasks: Task[];
}

const WEEK = 7 * 24 * 60 * 60 * 1000;

/** In progress (doing, blocked) · To do · Done this week. Dropped tasks and
 * those done before this week are not shown; `doneEarlier` counts the latter. */
export function groupTasks(
  tasks: Task[],
  now: Date = new Date(),
): { groups: TaskGroup[]; doneEarlier: number } {
  const recent = (t: Task) =>
    t.done_at != null && now.getTime() - new Date(t.done_at).getTime() < WEEK;
  const done = tasks.filter((t) => t.status === "done");
  const groups: TaskGroup[] = [
    {
      key: "progress",
      label: "In progress",
      tasks: tasks.filter(
        (t) => t.status === "doing" || t.status === "blocked",
      ),
    },
    {
      key: "todo",
      label: "To do",
      tasks: tasks.filter((t) => t.status === "todo"),
    },
    { key: "done", label: "Done this week", tasks: done.filter(recent) },
  ];
  return {
    groups: groups.filter((g) => g.tasks.length > 0),
    doneEarlier: done.length - done.filter(recent).length,
  };
}

/** "3 of 7 tasks done": dropped tasks are not part of the plan any more. */
export function progress(tasks: Task[]): { done: number; total: number } {
  const live = tasks.filter((t) => t.status !== "dropped");
  return {
    done: live.filter((t) => t.status === "done").length,
    total: live.length,
  };
}

/** The status words on the right of a row, as the plan, not an observation. */
export function statusWords(
  task: Task,
): { text: string; tone: "warn" | "good" | "bad" | "muted" } | null {
  if (task.status === "blocked") return { text: "Blocked", tone: "warn" };
  if (task.status === "doing") return { text: "Doing", tone: "good" };
  return null;
}

/** "Wed, Oct 21", "Overdue: Mon, Oct 19", or "No date". Dates are calendar
 * dates (YYYY-MM-DD): read as such, not as instants in some zone. */
export function dueWords(
  task: Pick<Task, "due_date" | "status">,
  now: Date = new Date(),
): { text: string; overdue: boolean } {
  if (!task.due_date) return { text: "No date", overdue: false };
  const [y, m, d] = task.due_date.split("-").map(Number);
  const date = new Date(Date.UTC(y!, (m ?? 1) - 1, d ?? 1));
  const text = new Intl.DateTimeFormat("en-US", {
    timeZone: "UTC",
    weekday: "short",
    month: "short",
    day: "numeric",
  }).format(date);
  const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
  const overdue = task.status !== "done" && task.due_date < today;
  return { text: overdue ? `Overdue: ${text}` : text, overdue };
}

/** Who owns it, for the chip: "You", or the agent/session/workflow named. */
export function ownerWords(owner: Owner | null): {
  label: string;
  source: string | null;
} | null {
  if (!owner) return null;
  if (owner.kind === "user") return { label: "You", source: null };
  const kind =
    owner.kind === "agent"
      ? "Agent"
      : owner.kind === "session"
        ? "Session"
        : "Workflow";
  return {
    label: owner.ref ? displayName(owner.ref) : kind,
    source: owner.ref,
  };
}

/** "claude-code" → "Claude Code", "codex" → "Codex". */
export function displayName(ref: string): string {
  return ref
    .split(/[-_\s]+/)
    .filter(Boolean)
    .map((w) => w[0]!.toUpperCase() + w.slice(1))
    .join(" ");
}
