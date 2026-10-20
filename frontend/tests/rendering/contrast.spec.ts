import { readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test, type Page } from "@playwright/test";

import { lowContrastText, type LowContrast } from "./contrast-probe";

/**
 * Phase 2.5 colour pass: every visible piece of text, in light AND dark, meets
 * WCAG AA contrast against what is actually painted behind it (4.5:1, or 3:1
 * for large text). Measured on the rendered production build, not inferred from
 * class names: a token can be right and its pairing wrong.
 *
 * The pages are given realistic data (pending actions, alerts, rules, sources,
 * firings, audit rows, sessions), because badges and status colours only render
 * when there is something to show. Long pages are scrolled, a screen at a time.
 *
 * Before the pass, this found 61 failures on the landing page in each theme,
 * black text on the dark sidebar on every workspace page, a light-only MCP
 * page, and muted and error text just under AA.
 */
const HOUR = 60 * 60 * 1000;
const now = () => new Date().toISOString();

const ACTION = {
  id: "a1",
  tool_name: "calendar_decline",
  plan_text: "I will decline 1 meeting: Standup",
  targets: ["Standup"],
  requester: "lead_agent",
  delegation_chain: [],
  expires_at: new Date(Date.now() + 4 * HOUR).toISOString(),
  thread_id: "t1",
  threshold_targets: 10,
  requires_typed_count: false,
  withheld: false,
};

const RULES = {
  engine_enabled: true,
  rules_error: null,
  version: "v1",
  writable: true,
  not_writable_reason: null,
  rules: [
    {
      id: "morning-briefing",
      type: "cron",
      enabled: true,
      match: { schedule: "45 8 * * 1-5", timezone: "America/New_York" },
      prompt: "Brief me as of {scheduled_at}.",
      destination: "auto",
      urgent: false,
      activity: "fired",
      last_evaluated_at: now(),
      last_evaluated: "recorded",
      last_fired_at: now(),
      last_outcome: "delivered",
    },
    {
      id: "blocked-session",
      type: "watcher",
      enabled: false,
      match: { event: "waiting-on-user" },
      prompt: "{project} is waiting: {last_message}",
      destination: "auto",
      urgent: false,
      activity: "never-evaluated",
      last_evaluated_at: null,
      last_evaluated: "not-recorded",
      last_fired_at: null,
      last_outcome: null,
    },
  ],
};

const FIRING = (outcome: string, reason: string) => ({
  at: now(),
  rule_id: "morning-briefing",
  event_type: "cron",
  event_id: `e-${outcome}`,
  outcome,
  reason,
  batch: "alone",
  batch_id: null,
  delivered_with: [],
});

const ROUTES: Record<string, unknown> = {
  "**/api/confirmations": { readable: true, error: "", actions: [ACTION] },
  "**/api/inbox/alerts": {
    waiting_count: 2,
    alerts: [
      {
        rule_id: "blocked-session",
        event_id: "s1",
        event_type: "watcher",
        at: now(),
        state: "waiting",
        reason: "quiet hours",
        thread_id: "t2",
      },
      {
        rule_id: "weekly-review",
        event_id: "w1",
        event_type: "cron",
        at: now(),
        state: "not-delivered",
        reason: "held past 2h",
        thread_id: null,
      },
      {
        rule_id: "morning-briefing",
        event_id: "m1",
        event_type: "cron",
        at: now(),
        state: "delivered",
        reason: "",
        thread_id: "t3",
      },
      {
        rule_id: "drift",
        event_id: "d1",
        event_type: "cron",
        at: now(),
        state: "suppressed",
        reason: "no longer true",
        thread_id: null,
      },
    ],
  },
  "**/api/triggers/rules": RULES,
  "**/api/triggers/firings": {
    firings: [
      FIRING("delivered", ""),
      FIRING("suppressed", "quiet hours 22:00-07:30"),
      FIRING("failed", "telegram 502"),
      FIRING("queued", "awaiting the coalescing window"),
    ],
  },
  "**/api/automations/templates": [],
  "**/api/policy/rules": {
    source_file: "rules.yaml",
    rules: [
      { pattern: "gmail_fetch_*", tier: 1, exceptions: [], source_line: 1 },
      {
        pattern: "calendar_delete_event",
        tier: 3,
        exceptions: [],
        source_line: 2,
      },
    ],
    unreadable: false,
    kept_previous: true,
    error: "line 4: not a list",
    threshold_targets: 10,
    expires_after_seconds: 14400,
  },
  "**/api/policy/audit": [
    {
      at: now(),
      actor: "default",
      tool: "calendar_delete_event",
      plan_as_stated: "I will delete 1 event: Standup",
      targets: ["Standup"],
      authorised_by: "worker-1",
      outcome: "executed",
      withheld: false,
    },
  ],
  "**/api/tool-sources*": {
    thread_id: null,
    failing: 1,
    connectors_available: true,
    sources: [
      {
        id: "local:session-watcher",
        name: "session-watcher",
        kind: "local",
        state: "live",
        tool_count: 2,
        error: null,
        selected: null,
      },
      {
        id: "local:dead-server",
        name: "dead-server",
        kind: "local",
        state: "unreachable",
        tool_count: null,
        error: "ConnectError: All connection attempts failed",
        selected: null,
      },
      {
        id: "local:filesystem",
        name: "filesystem",
        kind: "local",
        state: "disabled",
        tool_count: null,
        error: null,
        selected: null,
      },
      {
        id: "local:github",
        name: "github",
        kind: "local",
        state: "not-configured",
        tool_count: null,
        error: null,
        selected: null,
      },
      {
        id: "connector:GMAIL",
        name: "Gmail",
        kind: "connector",
        state: "authorised",
        tool_count: null,
        error: null,
        selected: null,
      },
      {
        id: "connector:SLACK",
        name: "Slack",
        kind: "connector",
        state: "not-authorised",
        tool_count: null,
        error: null,
        selected: null,
      },
    ],
  },
  "**/api/sessions": {
    reachable: true,
    unreachable_kind: null,
    unreachable_detail: null,
    observability: "live",
    staleness_seconds: 2,
    as_of: null,
    observe_only: true,
    observe_only_reason: "Sessions are observed, never controlled.",
    sessions: [
      {
        session_id: "s-0001",
        project: "omniHarness@main",
        display_state: "waiting-on-user",
        epistemic: "inferred",
        last_activity_at: now(),
        quiet_seconds: 120,
        summary: "Should I pin the fixture?",
        summary_provenance: "mechanical",
        relay_suppressed: false,
        withheld: false,
      },
      {
        session_id: "s-0003",
        project: "beta-site",
        display_state: "working",
        epistemic: "observed",
        last_activity_at: now(),
        quiet_seconds: 10,
        summary: "Writing the parser.",
        summary_provenance: "mechanical",
        relay_suppressed: false,
        withheld: false,
        agent: "codex",
        agent_label: "Codex",
        todos: [
          { title: "Parse records", status: "completed" },
          { title: "Write tests", status: "in_progress" },
          { title: "Ship", status: "pending" },
        ],
        files_changed: 3,
      },
      {
        session_id: "s-0002",
        project: "rallion",
        display_state: "failed",
        epistemic: "observed",
        last_activity_at: now(),
        quiet_seconds: 30,
        summary: "",
        summary_provenance: "mechanical",
        relay_suppressed: false,
        withheld: true,
      },
    ],
  },
};

const SERVER = (id: string, status: string) => ({
  id,
  name: `${id}-server`,
  language: "python",
  description: "Wraps an internal API.",
  status,
  phase: "deployed",
  approved: true,
  detected_secrets: [],
  egress_hosts: [],
  source_code: null,
  files: null,
  created_at: now(),
  updated_at: now(),
});
const TOOLKIT = (slug: string, status: string) => ({
  slug,
  name: slug,
  icon: "",
  category: "Productivity",
  description: `${slug} via Composio.`,
  status,
  account_display: status === "active" ? "me@example.com" : null,
});
const DAY = 24 * 60 * 60 * 1000;
const daysAgo = (d: number) => new Date(Date.now() - d * DAY).toISOString();
Object.assign(ROUTES, {
  "**/api/ledger/projects": [
    {
      id: "p1",
      name: "Beta launch",
      why: "Ship the public beta by Dec 1",
      status: "active",
      context: null,
      version: 1,
      created_at: now(),
      updated_at: now(),
      open_tasks: 2,
      overdue: 1,
      done_tasks: 1,
    },
  ],
  "**/api/ledger/projects/p1": {
    project: {
      id: "p1",
      name: "Beta launch",
      why: "Ship the public beta by Dec 1",
      status: "active",
      context: null,
      version: 1,
      created_at: now(),
      updated_at: now(),
    },
    goals: [
      {
        id: "g1",
        project_id: "p1",
        title: "Public beta live",
        definition_of_done: "anyone can sign up",
        target_date: "2026-12-01",
        version: 1,
        progress: { done: 1, total: 3 },
      },
    ],
    tasks: [
      {
        id: "t1",
        project_id: "p1",
        short_id: "T-1",
        title: "Landing page",
        status: "done",
        owner: null,
        due_date: "2026-10-01",
        goal_id: "g1",
        version: 1,
        done_at: now(),
      },
      {
        id: "t2",
        project_id: "p1",
        short_id: "T-2",
        title: "Waitlist form",
        status: "doing",
        owner: { kind: "agent", ref: null },
        due_date: "2026-10-02",
        goal_id: "g1",
        version: 1,
        done_at: null,
      },
      {
        id: "t3",
        project_id: "p1",
        short_id: "T-3",
        title: "Announcement",
        status: "blocked",
        owner: null,
        due_date: null,
        goal_id: null,
        version: 1,
        done_at: null,
      },
    ],
    notes: [
      {
        id: "n1",
        decided: "Use Resend for the waitlist",
        why: "simple API",
        thread_id: null,
        created_at: now(),
      },
    ],
    links: [
      {
        id: "l1",
        from_kind: "project",
        from_id: "p1",
        to_kind: "thread",
        to_ref: "thread-1",
        label: "Plan the beta",
      },
    ],
  },
  "**/api/memory": {
    version: "1.0",
    lastUpdated: daysAgo(1),
    user: {
      workContext: {
        summary: "Founder building OmniHarness.",
        updatedAt: daysAgo(3),
      },
      personalContext: {
        summary: "Prefers concise answers with a table first.",
        updatedAt: daysAgo(100),
      },
      topOfMind: {
        summary: "Building a retention dashboard. ".repeat(12),
        updatedAt: daysAgo(2),
      },
    },
    history: {
      recentMonths: {
        summary: "Shipped the trigger engine.",
        updatedAt: daysAgo(40),
      },
      earlierContext: { summary: "", updatedAt: "" },
      longTermBackground: { summary: "", updatedAt: "" },
    },
    facts: [
      {
        id: "f1",
        content: "Prefers tables over prose",
        category: "preference",
        confidence: 0.95,
        createdAt: daysAgo(10),
        source: "t1",
      },
      {
        id: "f2",
        content: "Lives in New York",
        category: "context",
        confidence: 0.9,
        createdAt: daysAgo(40),
        source: "t2",
      },
    ],
  },
  "**/api/mcp-studio/servers": {
    servers: [
      SERVER("weather", "deployed"),
      SERVER("crm", "failed"),
      SERVER("notes", "stopped"),
    ],
    total: 3,
  },
  "**/api/composio/catalog": {
    toolkits: [
      TOOLKIT("gmail", "active"),
      TOOLKIT("slack", "not_connected"),
      TOOLKIT("notion", "pending"),
    ],
  },
  "**/api/composio/connections": { connections: [] },
  "**/api/mcp/config": { mcp_servers: {} },
  "**/api/mcp-studio/servers/weather": SERVER("weather", "deployed"),
  "**/api/preferences/appearance": { appearance: "system", chosen: false },
});

const PAGES = [
  "/",
  "/workspace/chats/new",
  "/workspace/inbox",
  "/workspace/automations",
  "/workspace/automations/morning-briefing",
  "/workspace/agents",
  "/workspace/sessions",
  "/workspace/connections",
  "/workspace/projects",
  "/workspace/projects/p1",
  "/workspace/connections?tab=suite",
  "/workspace/settings/memory",
  "/workspace/settings/memory?tab=facts",
  "/workspace/mcp/new",
  "/workspace/settings/safety",
  "/workspace/settings/activity",
  "/workspace/settings/appearance",
  "/workspace/settings/account",
  // Feature 006: every other workspace page (see the coverage test below).
  "/workspace/chats",
  "/workspace/agents/new",
  "/workspace/agents/coder/chats/new",
  "/workspace/automations/new",
  "/workspace/mcp/weather",
  "/workspace/mcp/callback",
  "/workspace/workflows/w1",
  "/workspace/workflows/w1/runs/r1",
  "/workspace/settings/notification",
  "/workspace/settings/tools",
  "/workspace/settings/skills",
  "/workspace/settings/about",
  "/login",
  "/setup",
];

/** Workspace pages not audited, each with the reason. */
const NOT_AUDITED: Record<string, string> = {
  "/workspace": "redirects to /workspace/chats/new",
  "/workspace/confirmations": "redirects to /workspace/inbox",
  "/workspace/mcp": "redirects to /workspace/connections",
  "/workspace/policy": "redirects to /workspace/settings/safety",
  "/workspace/settings": "redirects to a settings section",
  "/workspace/settings/connections": "redirects to /workspace/connections",
  "/workspace/tool-sources": "redirects to /workspace/connections",
  "/workspace/triggers": "redirects to /workspace/automations",
  "/workspace/workflows": "redirects to /workspace/automations",
};

/** src/app/workspace/** /page.tsx as route patterns, dynamic segments as [x]. */
function workspaceRoutes(): string[] {
  const root = fileURLToPath(new URL("../../src/app", import.meta.url));
  const walk = (dir: string): string[] =>
    readdirSync(dir).flatMap((name) => {
      const path = join(dir, name);
      if (statSync(path).isDirectory()) return walk(path);
      return name === "page.tsx" ? [path] : [];
    });
  return walk(join(root, "workspace")).map(
    (f) => "/" + relative(root, f).replace(/\/?page\.tsx$/, ""),
  );
}

test("every workspace page is audited, or listed with the reason it is not", () => {
  const audited = PAGES.map((p) => p.split("?")[0]!);
  const routes = workspaceRoutes();
  expect(routes.length, "found no pages: the walk is blind").toBeGreaterThan(
    20,
  );
  const missing = routes.filter((route) => {
    if (route in NOT_AUDITED) return false;
    const re = new RegExp("^" + route.replace(/\[[^\]]+\]/g, "[^/]+") + "$");
    return !audited.some((p) => re.test(p));
  });
  expect(missing, "add these to PAGES (with stubs) or NOT_AUDITED").toEqual([]);
});

async function stub(page: Page) {
  for (const [pattern, body] of Object.entries(ROUTES)) {
    await page.route(pattern, (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(body),
      }),
    );
  }
}

/** Every screenful of the page, each probed once it has rendered. */
async function auditPage(page: Page): Promise<LowContrast[]> {
  const found = new Map<string, LowContrast>();
  const height = await page.evaluate(
    () => document.documentElement.scrollHeight,
  );
  for (let y = 0; y < height; y += 800) {
    await page.evaluate((top) => window.scrollTo(0, top), y);
    await page.waitForTimeout(400);
    for (const item of await page.evaluate(lowContrastText)) {
      found.set(`${item.text}|${item.cls}`, item);
    }
  }
  return [...found.values()];
}

for (const scheme of ["light", "dark"] as const) {
  test.describe(`${scheme} theme`, () => {
    test.use({ colorScheme: scheme, viewport: { width: 1280, height: 800 } });
    for (const path of PAGES) {
      test(`${path}: all text meets WCAG AA`, async ({ page }) => {
        await page.addInitScript((t) => {
          try {
            localStorage.setItem("theme", t);
          } catch {}
        }, scheme);
        await stub(page);
        await page.goto(path, { waitUntil: "networkidle" });
        const isDark = await page.evaluate(() =>
          document.documentElement.classList.contains("dark"),
        );
        expect(isDark, "the page did not take the theme").toBe(
          scheme === "dark",
        );
        const found = await auditPage(page);
        expect(
          found,
          found
            .map(
              (f) => `${f.ratio}/${f.need} "${f.text}" ${f.color} [${f.cls}]`,
            )
            .join("\n"),
        ).toEqual([]);
      });
    }
  });
}

test("POSITIVE CONTROL: the probe finds low contrast when it is there", async ({
  page,
}) => {
  await page.setContent(
    `<body style="background:#fff;margin:0">
       <p style="color:#bbb">pale grey on white</p>
       <p style="color:#111">dark on white</p>
       <div style="position:relative;height:40px">
         <div style="position:absolute;inset:0;background:#000"></div>
         <span style="position:absolute;left:4px;top:4px;color:#fff">white on an overlapping black sibling</span>
       </div>
     </body>`,
  );
  const found = await page.evaluate(lowContrastText);
  expect(found.map((f) => f.text)).toEqual(["pale grey on white"]);
});
