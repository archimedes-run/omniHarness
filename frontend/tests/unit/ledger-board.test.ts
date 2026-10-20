import { describe, expect, it } from "vitest";

import {
  dueWords,
  groupTasks,
  ownerWords,
  progress,
  statusWords,
} from "@/core/ledger/board";
import type { Task } from "@/core/ledger/types";

const NOW = new Date("2026-10-20T15:00:00");
const task = (patch: Partial<Task>): Task => ({
  id: patch.title ?? "t",
  project_id: "p",
  short_id: "T-1",
  title: "t",
  status: "todo",
  owner: null,
  due_date: null,
  goal_id: null,
  version: 1,
  done_at: null,
  ...patch,
});

describe("grouping", () => {
  it("puts doing and blocked in progress, and only this week's done", () => {
    const { groups, doneEarlier } = groupTasks(
      [
        task({ title: "a", status: "doing" }),
        task({ title: "b", status: "blocked" }),
        task({ title: "c" }),
        task({ title: "d", status: "done", done_at: "2026-10-19T10:00:00Z" }),
        task({ title: "e", status: "done", done_at: "2026-09-01T10:00:00Z" }),
        task({ title: "f", status: "dropped" }),
      ],
      NOW,
    );
    expect(groups.map((g) => [g.label, g.tasks.map((t) => t.title)])).toEqual([
      ["In progress", ["a", "b"]],
      ["To do", ["c"]],
      ["Done this week", ["d"]],
    ]);
    expect(doneEarlier).toBe(1);
  });

  it("counts progress without dropped tasks", () => {
    expect(
      progress([
        task({ status: "done" }),
        task({}),
        task({ status: "dropped" }),
      ]),
    ).toEqual({ done: 1, total: 2 });
  });
});

describe("wording", () => {
  it("says the plan's status, never an observation", () => {
    expect(statusWords(task({ status: "doing" }))?.text).toBe("Doing");
    expect(statusWords(task({ status: "blocked" }))?.text).toBe("Blocked");
    expect(statusWords(task({}))).toBeNull();
  });

  it("reads a due date as a calendar date, and flags it overdue", () => {
    expect(dueWords(task({ due_date: "2026-10-21" }), NOW)).toEqual({
      text: "Wed, Oct 21",
      overdue: false,
    });
    expect(dueWords(task({ due_date: "2026-10-19" }), NOW)).toEqual({
      text: "Overdue: Mon, Oct 19",
      overdue: true,
    });
    expect(dueWords(task({}), NOW).text).toBe("No date");
  });

  it("names the owner", () => {
    expect(ownerWords({ kind: "user", ref: null })?.label).toBe("You");
    expect(ownerWords({ kind: "agent", ref: "codex" })).toEqual({
      label: "Codex",
      source: "codex",
    });
    expect(ownerWords(null)).toBeNull();
  });
});
