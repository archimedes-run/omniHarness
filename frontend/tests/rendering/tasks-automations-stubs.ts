import type { Page } from "@playwright/test";
const now = Date.now();
const iso = (ms: number) => new Date(ms).toISOString();
const DAY = 86400000;
const json = (body: unknown) => ({
  status: 200,
  contentType: "application/json",
  body: JSON.stringify(body),
});
const rule = (
  id: string,
  name: string,
  type: string,
  match: object,
  enabled = true,
  extra = {},
) => ({
  id,
  name,
  type,
  enabled,
  match,
  prompt: "Brief me as of {scheduled_at}.",
  destination: id === "morning-brief" ? "remote" : "auto",
  urgent: false,
  activity: "fired",
  last_evaluated_at: iso(now - 120000),
  last_evaluated: "recorded",
  last_fired_at: iso(now - DAY),
  last_outcome: "delivered",
  next_run: !enabled ? "off" : type === "cron" ? "scheduled" : "on-event",
  next_run_at: type === "cron" && enabled ? "2026-10-21T08:45:00-04:00" : null,
  deliver_at: type === "cron" && enabled ? "2026-10-21T08:45:00-04:00" : null,
  held_for_quiet_hours: false,
  timezone: "America/New_York",
  ...extra,
});
export async function stubAutomations(page: Page) {
  await page.route("**/api/triggers/rules", (r) =>
    r.fulfill(
      json({
        engine_enabled: true,
        rules_error: null,
        version: "v1",
        writable: true,
        not_writable_reason: null,
        quiet_hours: {
          enabled: true,
          start: "22:00",
          end: "07:00",
          timezone: "America/New_York",
        },
        rules: [
          rule("morning-brief", "Morning brief", "cron", {
            schedule: "45 8 * * 1-5",
            timezone: "America/New_York",
          }),
          rule("blocked-session", "Blocked session alert", "watcher", {
            event: "waiting-on-user",
          }),
          rule("evening-wrap-up", "Evening wrap-up", "cron", {
            schedule: "0 18 * * 1-5",
            timezone: "America/New_York",
          }),
          rule(
            "weekly-review",
            "Weekly review",
            "cron",
            { schedule: "0 16 * * 5", timezone: "America/New_York" },
            false,
          ),
        ],
      }),
    ),
  );
  const run = (day: number, kind: string, extra = {}) => ({
    event_id: `e${day}`,
    at: `2026-10-${day}T08:45:00-04:00`,
    kind,
    settled_at: `2026-10-${day}T12:46:00+00:00`,
    reason: "",
    held_because: null,
    held_reason: "",
    delivered_with: [],
    batch_not_recorded: false,
    thread_id: "t1",
    ...extra,
  });
  await page.route("**/api/triggers/rules/*/runs", (r) =>
    r.fulfill(
      json({
        rule_id: "morning-brief",
        runs: [
          run(20, "delivered"),
          run(16, "held-then-delivered", {
            held_because: "mid-conversation",
            settled_at: "2026-10-16T13:02:00+00:00",
          }),
          run(15, "delivered-with-others", {
            delivered_with: [{ rule_id: "blocked-session", event_id: "s1" }],
          }),
          run(14, "failed", {
            reason: "gave up after 3 attempts: model timeout",
            thread_id: null,
          }),
        ],
      }),
    ),
  );
  await page.route("**/api/automations/templates", (r) =>
    r.fulfill(
      json([
        {
          template: "morning-brief",
          title: "Morning brief",
          description: "",
          rule: {},
        },
        {
          template: "blocked-session",
          title: "Blocked coding session",
          description: "",
          rule: {},
        },
        {
          template: "weekly-review",
          title: "Weekly review",
          description: "",
          rule: {},
        },
      ]),
    ),
  );
}

const project = (id: string, name: string, open: number) => ({
  id,
  name,
  why: null,
  status: "active",
  context: null,
  version: 1,
  created_at: iso(now),
  updated_at: iso(id === "p1" ? now : now - 3 * DAY),
  open_tasks: open,
  overdue: 0,
  done_tasks: 1,
});
const task = (id: string, title: string, patch: object = {}) => ({
  id,
  project_id: "p1",
  short_id: id,
  title,
  status: "todo",
  owner: null,
  due_date: null,
  goal_id: null,
  version: 1,
  done_at: null,
  ...patch,
});
export async function stubTasks(page: Page) {
  await page.route("**/api/ledger/projects", (r) =>
    r.fulfill(
      json([
        project("p1", "OmniHarness", 4),
        project("p2", "HackMIT 2026 judging", 3),
        project("p3", "DarcyIQ walkthrough", 2),
        project("p4", "Personal", 5),
      ]),
    ),
  );
  await page.route("**/api/ledger/projects/*", (r) =>
    r.fulfill(
      json({
        project: project("p1", "OmniHarness", 4),
        goals: [
          {
            id: "g1",
            project_id: "p1",
            title: "Feature 005 Project Ledger shipped",
            definition_of_done: "",
            target_date: null,
            version: 1,
            progress: { done: 1, total: 5 },
          },
        ],
        tasks: [
          task("t1", "Codex adapter for the session watcher", {
            status: "blocked",
            owner: { kind: "agent", ref: "codex" },
          }),
          task(
            "t2",
            "Native todo lists, applied only after a confirmed result",
            { status: "doing", owner: { kind: "agent", ref: "claude-code" } },
          ),
          task("t3", "Review slices 1 and 2", {
            owner: { kind: "user", ref: null },
            due_date: "2026-10-21",
          }),
          task("t4", "Live Tier 3 check on a throwaway calendar event", {
            owner: { kind: "user", ref: null },
          }),
          task("t5", "Phase 2.6 polish", {
            status: "done",
            done_at: iso(now - DAY),
            owner: { kind: "agent", ref: "claude-code" },
          }),
        ],
        notes: [
          {
            id: "n1",
            decided: "Ship the ledger before evidence",
            why: "Evidence needs tasks to attach to",
            thread_id: null,
            created_at: iso(now),
          },
        ],
        links: [
          {
            id: "l1",
            from_kind: "task",
            from_id: "t4",
            to_kind: "thread",
            to_ref: "th1",
            label: null,
          },
        ],
      }),
    ),
  );
  await page.route("**/threads/search", (r) =>
    r.fulfill(
      json([
        {
          thread_id: "th1",
          updated_at: iso(now),
          values: { title: "Calendar cleanup" },
          metadata: {},
        },
      ]),
    ),
  );
}
