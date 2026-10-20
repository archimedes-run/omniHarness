import { mkdirSync } from "node:fs";

import { expect, test, type Page, type Route } from "@playwright/test";

import { lowContrastText, type LowContrast } from "./contrast-probe";

/**
 * Home (Feature 005 Slice 3, built to Feature 006's Main board): greeting,
 * Waiting on you, While you were away, Projects, Coding sessions, Upcoming,
 * What moved today, and the chat bar at the bottom. Every block keeps "empty"
 * apart from "can't tell". NO BACKEND: the API is stubbed, statefully where
 * Home writes (dismissals, the display name).
 */
const SHOTS = process.env.HOME_SHOTS_DIR;
const HOUR = 3_600_000;
const ago = (ms: number) => new Date(Date.now() - ms).toISOString();
const ahead = (ms: number) => new Date(Date.now() + ms).toISOString();

const json = (route: Route, body: unknown, status = 200) =>
  route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });

const session = (
  id: string,
  project: string,
  state: string,
  agent: "claude" | "codex",
  quiet = 30_000,
) => ({
  session_id: id,
  project,
  display_state: state,
  epistemic: state === "waiting-on-user" ? "inferred" : "observed",
  last_activity_at: ago(quiet),
  quiet_seconds: quiet / 1000,
  summary:
    state === "waiting-on-user"
      ? "Should I pin the fixture version or rewrite the fixture?"
      : "",
  summary_provenance: "reported",
  relay_suppressed: false,
  withheld: false,
  agent,
  agent_label: agent === "claude" ? "Claude Code" : "Codex",
});

const SESSIONS = {
  reachable: true,
  unreachable_kind: null,
  unreachable_detail: null,
  observability: "live",
  staleness_seconds: 12,
  as_of: ago(12_000),
  sessions: [
    session("s1", "omniHarness@main", "working", "claude"),
    session(
      "s2",
      "omniHarness@005-project-ledger",
      "waiting-on-user",
      "codex",
      6 * 60_000,
    ),
    session("s3", "Rallion@main", "completed", "claude", 22 * 60_000),
  ],
  observe_only: true,
  observe_only_reason: "Observe only.",
};

const ACTION = {
  id: "a1",
  tool_name: "googlecalendar_delete_event",
  plan_text: "Delete event “E2E test, delete me” (Tue 3:00 PM)",
  targets: ["E2E test, delete me"],
  requester: "lead_agent",
  delegation_chain: [],
  expires_at: ahead(3 * HOUR + 41 * 60_000),
  thread_id: "t-cal",
  threshold_targets: 10,
  requires_typed_count: false,
  withheld: false,
};

const alert = (rule: string, event: string, state: string) => ({
  rule_id: rule,
  event_id: event,
  event_type: "cron",
  at: ago(HOUR),
  state,
  reason: state === "not-delivered" ? "held past 2h" : "quiet hours",
  thread_id: null,
});

const project = (
  id: string,
  name: string,
  open: number,
  done: number,
  extra: Record<string, unknown> = {},
) => ({
  id,
  name,
  why: null,
  status: "active",
  context: null,
  version: 1,
  created_at: ago(HOUR),
  updated_at: ago(HOUR),
  open_tasks: open,
  overdue: 0,
  done_tasks: done,
  next_due: null,
  ...extra,
});

const PROJECTS = [
  project("p1", "OmniHarness", 4, 3, {
    why: "Feature 005 · Slice 1 in progress",
  }),
  project("p2", "HackMIT 2026 judging", 3, 1, { next_due: "2026-10-23" }),
  project("p3", "DarcyIQ walkthrough", 0, 0),
];

const UPCOMING = {
  engine_enabled: true,
  rules_error: null,
  runs: [
    {
      rule_id: "morning-briefing",
      title: "Morning briefing",
      prompt: "Brief me",
      at: ahead(14 * HOUR),
      schedule: "45 8 * * *",
      timezone: null,
    },
    {
      rule_id: "weekly-review",
      title: "Weekly review",
      prompt: "Review",
      at: ahead(80 * HOUR),
      schedule: "0 17 * * 5",
      timezone: null,
      held_until: ahead(90 * HOUR),
    },
  ],
  calendar: {
    state: "ok",
    detail: null,
    events: [
      {
        title: "DarcyIQ sync with Mike Flores",
        start: ahead(20 * HOUR),
        all_day: false,
      },
    ],
  },
};

const TODAY = {
  items: [
    {
      at: ago(HOUR),
      source: "ledger",
      text: "Task done in OmniHarness: Ship Home",
      by: "you",
      project_id: "p1",
      thread_id: null,
      known: "observed",
      url: null,
    },
    {
      at: ago(HOUR / 2),
      source: "github",
      text: "PR #41 merged in archimedes-run/omniHarness: sidebar",
      by: null,
      project_id: null,
      thread_id: null,
      known: "reported",
      url: "https://github.com/archimedes-run/omniHarness/pull/41",
    },
    {
      at: ago(2 * HOUR),
      source: "automation",
      text: "Morning briefing delivered",
      by: null,
      project_id: null,
      thread_id: "t-m",
      known: "observed",
      url: null,
    },
  ],
  sources: { ledger: "ok", automations: "ok", sessions: "ok", github: "ok" },
};

interface Options {
  empty?: boolean;
  broken?: boolean;
  displayName?: string | null;
  promptDismissed?: boolean;
  calendarDown?: boolean;
}

/** Stubs Home's API. Returns the server-side state Home writes to. */
async function serve(page: Page, opts: Options = {}) {
  const state = {
    dismissed: new Set<string>(),
    promptDismissed: opts.promptDismissed ?? true,
    displayName: opts.displayName === undefined ? "Rishabh" : opts.displayName,
    posts: [] as unknown[],
  };
  const alerts = opts.empty
    ? []
    : [
        alert("weekly-review", "w1", "not-delivered"),
        alert("blocked-session", "b1", "waiting"),
      ];
  const fail = (route: Route) => json(route, { detail: "boom" }, 500);

  await page.route("**/api/confirmations", (route) =>
    opts.broken
      ? json(route, { actions: [], readable: false, error: "store unreadable" })
      : json(route, {
          actions: opts.empty ? [] : [ACTION],
          readable: true,
          error: "",
        }),
  );
  await page.route("**/api/inbox/alerts", (route) => {
    if (opts.broken) return fail(route);
    const list = alerts.map((a) => ({
      ...a,
      dismissed: state.dismissed.has(`${a.rule_id}:${a.event_id}`),
    }));
    return json(route, {
      alerts: list,
      waiting_count: list.filter((a) => !a.dismissed).length,
      dismissals_readable: true,
    });
  });
  await page.route("**/api/sessions", (route) =>
    opts.broken
      ? json(route, {
          ...SESSIONS,
          reachable: false,
          unreachable_kind: "unreachable",
          observability: null,
          sessions: null,
        })
      : json(route, opts.empty ? { ...SESSIONS, sessions: [] } : SESSIONS),
  );
  await page.route("**/api/ledger/projects", (route) =>
    opts.broken ? fail(route) : json(route, opts.empty ? [] : PROJECTS),
  );
  await page.route("**/api/home/upcoming", (route) =>
    opts.broken
      ? fail(route)
      : json(
          route,
          opts.empty
            ? {
                ...UPCOMING,
                runs: [],
                calendar: { state: "not-set-up", detail: null, events: [] },
              }
            : opts.calendarDown
              ? {
                  ...UPCOMING,
                  calendar: {
                    state: "unavailable",
                    detail: "Google Calendar did not answer",
                    events: [],
                  },
                }
              : UPCOMING,
        ),
  );
  await page.route(/\/api\/home\/today/, (route) =>
    opts.broken
      ? fail(route)
      : json(route, opts.empty ? { ...TODAY, items: [] } : TODAY),
  );
  await page.route("**/api/home/dismissals", async (route) => {
    if (route.request().method() === "POST") {
      const body = route.request().postDataJSON() as {
        kind: string;
        keys?: string[];
      };
      state.posts.push(body);
      if (body.kind === "alert")
        body.keys?.forEach((k) => state.dismissed.add(k));
      else state.promptDismissed = true;
    }
    return json(route, {
      alert_keys: [...state.dismissed],
      name_prompt_dismissed: state.promptDismissed,
    });
  });
  const prefs = () => ({
    appearance: "system",
    appearance_chosen: false,
    display_name: state.displayName,
    display_name_effective: state.displayName ?? "rishabh.sharma1103",
  });
  await page.route("**/api/preferences/display-name", (route) => {
    const body = route.request().postDataJSON() as { display_name: string };
    state.displayName = body.display_name;
    return json(route, prefs());
  });
  await page.route("**/api/preferences", (route) => json(route, prefs()));
  return state;
}

async function inTheme(page: Page, scheme: "light" | "dark") {
  await page.emulateMedia({ colorScheme: scheme });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.addInitScript((t) => {
    try {
      localStorage.setItem("theme", t);
    } catch {}
  }, scheme);
}

async function noLowContrast(page: Page) {
  const found = new Map<string, LowContrast>();
  const height = await page.evaluate(
    () =>
      document.querySelector('[data-testid="home-scroll"]')?.scrollHeight ?? 0,
  );
  for (let y = 0; y <= height; y += 700) {
    await page.evaluate((top) => {
      const shell = document.querySelector('[data-testid="home-scroll"]');
      if (shell) shell.scrollTop = top;
    }, y);
    await page.waitForTimeout(300);
    for (const f of await page.evaluate(lowContrastText))
      found.set(`${f.text}|${f.cls}`, f);
  }
  const list = [...found.values()];
  expect(
    list,
    list
      .map((f) => `${f.ratio}/${f.need} "${f.text}" ${f.color} [${f.cls}]`)
      .join("\n"),
  ).toEqual([]);
}

test("the board's blocks render from real data", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await serve(page);
  await page.goto("/workspace/home");

  await expect(page.getByTestId("greeting")).toHaveText(
    /^Good (morning|afternoon|evening), Rishabh$/,
  );
  // 1 session waiting + 1 approval + 2 alerts missed.
  await expect(page.getByTestId("needs-you")).toContainText(
    "4 things need you",
  );

  const waiting = page.getByTestId("waiting-on-you");
  await expect(waiting.getByTestId("session")).toHaveCount(1);
  await expect(waiting.getByTestId("session")).toContainText(
    "Codex · omniHarness@005-project-ledger",
  );
  await expect(waiting.getByTestId("known-by")).toHaveText(
    "Inferred · 6 min ago",
  );
  await expect(waiting.getByRole("img", { name: "OpenAI logo" })).toBeVisible();
  await expect(
    waiting.getByRole("link", { name: "Open session" }),
  ).toBeVisible();
  const approval = waiting.getByTestId("pending-action");
  await expect(approval).toContainText("Delete event “E2E test, delete me”");
  await expect(approval.getByTestId("remaining")).toHaveText(/^3h 4\dm left$/);
  await expect(approval.getByTestId("decline")).toBeEnabled();
  await expect(approval.getByTestId("confirm")).toBeEnabled();

  const projects = page.getByTestId("home-projects");
  await expect(projects.getByTestId("home-project")).toHaveCount(3);
  await expect(projects).toContainText("3 of 7 tasks");
  await expect(projects).toContainText("Feature 005 · Slice 1 in progress");
  await expect(projects).toContainText("Due Fri, Oct 23");
  await expect(projects).toContainText("No task list yet");
  await expect(projects.getByRole("progressbar")).toHaveCount(2);

  const sessions = page.getByTestId("home-sessions");
  await expect(sessions.getByTestId("home-session-status")).toHaveText([
    "Working",
    "Looks like it's waiting on you",
    "Finished 22 min ago",
  ]);
  await expect(
    sessions.getByRole("img", { name: "Anthropic logo" }),
  ).toHaveCount(2);
  await expect(sessions.getByTestId("watcher-line")).toHaveText(
    "Watcher live · updated 12s ago",
  );

  const upcoming = page.getByTestId("home-upcoming");
  await expect(upcoming.getByTestId("home-upcoming-run")).toHaveCount(2);
  await expect(upcoming.getByTestId("home-upcoming-event")).toContainText(
    "DarcyIQ sync with Mike Flores",
  );
  // Soonest first: the briefing (14 h), the meeting (20 h), the review.
  await expect(
    upcoming.locator('[data-testid^="home-upcoming-"]').first(),
  ).toContainText("Morning briefing");
  await expect(upcoming.getByTestId("home-upcoming-run").nth(1)).toContainText(
    "(quiet hours)",
  );
  await expect(upcoming.getByTestId("home-upcoming-calendar")).toHaveText(
    "Calendar · Google Calendar, next 7 days",
  );

  const moved = page.getByTestId("home-moved");
  await expect(moved.getByTestId("home-moved-item")).toHaveCount(3);
  // How each line is known, in words.
  await expect(moved.getByTestId("known")).toHaveText([
    " · observed",
    " · reported",
    " · observed",
  ]);
  await expect(moved).toContainText("Task done in OmniHarness: Ship Home");

  // The chat bar is at the bottom, 816 px at most.
  const bar = page.getByTestId("home-chat-bar");
  await expect(bar).toBeVisible();
  const box = (await bar.boundingBox())!;
  expect(box.width).toBeLessThanOrEqual(816);
  expect(box.y + box.height).toBeGreaterThan(900 - 80);
  await expect(page.getByTestId("name-prompt")).toHaveCount(0);
});

test("a calendar that cannot be read is can't-tell; one not connected is not set up", async ({
  page,
}) => {
  await serve(page, { calendarDown: true });
  await page.goto("/workspace/home");
  await expect(
    page.getByTestId("home-upcoming-calendar-unreadable"),
  ).toContainText("did not answer");
  await expect(page.getByTestId("home-upcoming-event")).toHaveCount(0);
  await page.unrouteAll();
  await serve(page, { empty: true });
  await page.goto("/workspace/home");
  await expect(page.getByTestId("home-upcoming-calendar")).toHaveText(
    "Calendar · Not set up",
  );
});

test("empty is said plainly, and is not can't-tell", async ({ page }) => {
  await serve(page, { empty: true });
  await page.goto("/workspace/home");
  await expect(page.getByTestId("needs-you")).toContainText(
    "Nothing needs you",
  );
  for (const id of [
    "empty",
    "no-sessions-waiting",
    "no-alerts",
    "home-projects-empty",
    "home-sessions-empty",
    "home-upcoming-empty",
    "home-moved-empty",
  ]) {
    await expect(page.getByTestId(id), id).toBeVisible();
  }
  await expect(page.locator('[data-state="cant-tell"]')).toHaveCount(0);
  await expect(page.getByTestId("unreadable")).toHaveCount(0);
});

test("a source it cannot read is can't-tell, never empty", async ({ page }) => {
  await serve(page, { broken: true });
  await page.goto("/workspace/home");
  await expect(page.getByTestId("needs-you")).toContainText(
    "Can't tell yet what needs you",
  );
  for (const id of [
    "unreadable",
    "sessions-unreadable",
    "alerts-unreadable",
    "home-projects-unreadable",
    "home-sessions-unreadable",
    "home-upcoming-unreadable",
    "home-moved-unreadable",
  ]) {
    await expect(page.getByTestId(id), id).toBeVisible();
  }
  for (const id of [
    "empty",
    "no-sessions-waiting",
    "no-alerts",
    "home-projects-empty",
    "home-sessions-empty",
    "home-upcoming-empty",
    "home-moved-empty",
  ]) {
    await expect(page.getByTestId(id), id).toHaveCount(0);
  }
});

test("a dismissed alert is kept on the server: it stays gone after a reload, and the badge drops", async ({
  page,
}) => {
  const state = await serve(page);
  await page.goto("/workspace/home");
  const away = page.getByTestId("alerts-waiting").getByTestId("alert");
  await expect(away).toHaveCount(2);
  await expect(page.getByTestId("inbox-badge")).toHaveText("3");

  await page.getByRole("button", { name: "Dismiss weekly-review" }).click();
  await expect(away).toHaveCount(1);
  await expect(page.getByTestId("inbox-badge")).toHaveText("2");
  expect(state.posts).toEqual([{ kind: "alert", keys: ["weekly-review:w1"] }]);

  await page.reload();
  await expect(
    page.getByTestId("alerts-waiting").getByTestId("alert"),
  ).toHaveCount(1);
  await expect(page.getByTestId("inbox-badge")).toHaveText("2");
  await page.getByRole("button", { name: "Dismiss blocked-session" }).click();
  await expect(page.getByTestId("no-alerts")).toBeVisible();
  await expect(page.getByText("on every device")).toBeVisible();
});

test("the name is asked once: Not now is remembered on the server", async ({
  page,
}) => {
  const state = await serve(page, {
    displayName: null,
    promptDismissed: false,
  });
  await page.goto("/workspace/home");
  // The fallback (the email's local part) until a name is chosen.
  await expect(page.getByTestId("greeting")).toContainText(
    "rishabh.sharma1103",
  );
  await expect(page.getByTestId("name-prompt")).toBeVisible();
  await page.getByTestId("name-prompt-not-now").click();
  await expect(page.getByTestId("name-prompt")).toHaveCount(0);
  expect(state.posts).toEqual([{ kind: "name-prompt" }]);
  await page.reload();
  await expect(page.getByTestId("greeting")).toBeVisible();
  await expect(page.getByTestId("needs-you")).toBeVisible();
  await expect(page.getByTestId("name-prompt")).toHaveCount(0);
});

test("saving a name greets you by it at once", async ({ page }) => {
  await serve(page, { displayName: null, promptDismissed: false });
  await page.goto("/workspace/home");
  await page.getByLabel("What should I call you?").fill("Rishabh");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByTestId("greeting")).toHaveText(/, Rishabh$/);
  await expect(page.getByTestId("name-prompt")).toHaveCount(0);
});

for (const scheme of ["light", "dark"] as const) {
  test(`${scheme}: Home meets WCAG AA, with the name prompt`, async ({
    page,
  }) => {
    await inTheme(page, scheme);
    await serve(page, { displayName: null, promptDismissed: false });
    await page.goto("/workspace/home", { waitUntil: "networkidle" });
    expect(
      await page.evaluate(() =>
        document.documentElement.classList.contains("dark"),
      ),
    ).toBe(scheme === "dark");
    await expect(page.getByTestId("home-chat-bar")).toBeVisible();
    await expect(page.getByTestId("home-session")).toHaveCount(3);
    await noLowContrast(page);
  });

  test(`${scheme}: Home's can't-tell states meet WCAG AA`, async ({ page }) => {
    await inTheme(page, scheme);
    await serve(page, { broken: true });
    await page.goto("/workspace/home", { waitUntil: "networkidle" });
    await expect(page.getByTestId("home-moved-unreadable")).toBeVisible();
    if (SHOTS) {
      mkdirSync(SHOTS, { recursive: true });
      await page.screenshot({ path: `${SHOTS}/home-cant-tell-${scheme}.png` });
    }
    await noLowContrast(page);
  });

  test(`${scheme}: screenshot of Home as the board shows it`, async ({
    page,
  }) => {
    test.skip(!SHOTS, "set HOME_SHOTS_DIR to save review screenshots");
    await inTheme(page, scheme);
    await serve(page);
    await page.goto("/workspace/home", { waitUntil: "networkidle" });
    await expect(page.getByTestId("home-session")).toHaveCount(3);
    await page.waitForTimeout(500);
    await page.screenshot({ path: `${SHOTS}/home-live-${scheme}.png` });
    await page
      .getByTestId("home-scroll")
      .evaluate((el) => el.scrollTo(0, el.scrollHeight));
    await page.waitForTimeout(300);
    await page.screenshot({
      path: `${SHOTS}/home-live-${scheme}-scrolled.png`,
    });
  });
}
