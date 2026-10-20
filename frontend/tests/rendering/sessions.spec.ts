import { expect, test, type Page } from "@playwright/test";

/**
 * T069 — the sessions surface, asserted against what renders (SC-006, SC-007).
 *
 * NO BACKEND: /api/sessions is intercepted. The four watcher conditions, over
 * the real watcher, are pytest's (tests/gateway/test_sessions_router.py).
 */

function session(state: string, epistemic: string, project: string) {
  return {
    session_id: `${project}-0000`,
    project,
    display_state: state,
    epistemic,
    last_activity_at: null,
    quiet_seconds: 120,
    summary: "",
    summary_provenance: "mechanical",
    relay_suppressed: false,
    withheld: false,
  };
}

const LIVE = {
  reachable: true,
  unreachable_kind: null,
  unreachable_detail: null,
  observability: "live",
  staleness_seconds: 2,
  as_of: null,
  observe_only: true,
  observe_only_reason: "Sessions are observed, never controlled.",
  sessions: [
    session("waiting-on-user", "inferred", "darcy-repo"),
    session("completed", "observed", "rallion"),
  ],
};

async function serve(page: Page, body: Record<string, unknown>) {
  await page.route("**/api/sessions", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(body),
    }),
  );
  await page.goto("/workspace/sessions");
}

test("with the watcher stopped the page says sessions cannot be seen, and renders no list (SC-006)", async ({
  page,
}) => {
  await serve(page, {
    ...LIVE,
    reachable: false,
    unreachable_kind: "unreachable",
    unreachable_detail: "ConnectError",
    observability: null,
    sessions: null,
  });

  await expect(page.getByTestId("watcher-health")).toHaveAttribute(
    "data-health",
    "cannot-see",
  );
  await expect(page.getByTestId("watcher-health")).toContainText(
    "cannot see your sessions",
  );
  await expect(page.getByTestId("empty")).toHaveCount(0);
  await expect(page.getByTestId("session")).toHaveCount(0);
});

test("a waiting session differs from a finished one without reading the text (SC-007)", async ({
  page,
}) => {
  await serve(page, LIVE);

  const waiting = page.locator(
    '[data-testid="session"][data-state="waiting-on-user"]',
  );
  const finished = page.locator(
    '[data-testid="session"][data-state="completed"]',
  );
  const border = (l: typeof waiting) =>
    l.evaluate((el) => getComputedStyle(el).borderTopStyle);
  expect(await border(waiting)).toBe("dashed");
  expect(await border(finished)).toBe("solid");
  await expect(waiting.getByTestId("epistemic-icon")).toHaveAttribute(
    "aria-label",
    "inferred",
  );
  await expect(finished.getByTestId("epistemic-icon")).toHaveAttribute(
    "aria-label",
    "observed",
  );
});

test("stale data says how stale, and still shows the last-known sessions", async ({
  page,
}) => {
  await serve(page, {
    ...LIVE,
    observability: "stale",
    staleness_seconds: 7200,
  });

  await expect(page.getByTestId("watcher-health")).toHaveAttribute(
    "data-health",
    "stale",
  );
  await expect(page.getByTestId("watcher-health")).toContainText(
    "Last seen 2 h ago",
  );
  await expect(page.getByTestId("session")).toHaveCount(2);
});

test("observe-only is stated, so the missing controls read as a property (FR-015)", async ({
  page,
}) => {
  await serve(page, LIVE);

  await expect(page.getByTestId("observe-only")).toContainText(
    "observed, never controlled",
  );
});

test("a summary that failed redaction shows as withheld, not as blank (FR-031, SC-015)", async ({
  page,
}) => {
  await serve(page, {
    ...LIVE,
    sessions: [
      {
        ...session("working", "observed", "darcy-repo"),
        summary:
          "Withheld: this could not be safely redacted for display. Check it locally.",
        withheld: true,
      },
    ],
  });

  await expect(page.getByTestId("withheld")).toBeVisible();
  await expect(page.getByTestId("withheld")).toContainText("Withheld");
});

test("a watcher that did not answer in time shows its last answer, labelled with its age", async ({
  page,
}) => {
  await serve(page, {
    ...LIVE,
    reachable: false,
    unreachable_kind: "unreachable",
    unreachable_detail: "TimeoutError",
    last_known_age_seconds: 40,
  });

  await expect(page.getByTestId("watcher-health")).toHaveAttribute(
    "data-health",
    "last-known",
  );
  await expect(page.getByTestId("watcher-health")).toContainText("40s ago");
  await expect(page.getByTestId("session")).toHaveCount(2);
});

const CODEX = {
  ...session("working", "observed", "beta-site"),
  agent: "codex",
  agent_label: "Codex",
  todos: [
    { title: "Parse records", status: "completed" },
    { title: "Write tests", status: "in_progress" },
    { title: "Ship", status: "pending" },
  ],
  files_changed: 3,
};

test("Claude Code and Codex sessions share one list, each labelled by agent, with its task progress (Feature 005)", async ({
  page,
}) => {
  await serve(page, {
    ...LIVE,
    sessions: [
      {
        ...session("completed", "observed", "omniHarness"),
        agent: "claude",
        agent_label: "Claude Code",
        todos: null,
      },
      CODEX,
    ],
  });
  const rows = page.getByTestId("session");
  await expect(rows).toHaveCount(2);
  await expect(rows.nth(0).getByTestId("agent")).toHaveText("Claude Code");
  await expect(rows.nth(1).getByTestId("agent")).toHaveText("Codex");
  await expect(rows.nth(0).getByTestId("plan")).toHaveCount(0);

  const plan = rows.nth(1).getByTestId("plan");
  await expect(plan.getByTestId("plan-progress")).toHaveText("Tasks 1 of 3");
  await expect(plan).toContainText("Write tests");
  await plan.locator("summary").click();
  await expect(plan.locator('[data-status="pending"]')).toHaveText("Ship");
  await expect(rows.nth(1)).toContainText("3 files changed");
});

test("an agent whose files cannot be read says so, and is never just absent (FR-026)", async ({
  page,
}) => {
  await serve(page, {
    ...LIVE,
    agents: [
      {
        agent: "claude",
        label: "Claude Code",
        readable: true,
        reason: null,
        drift: 0,
      },
      {
        agent: "codex",
        label: "Codex",
        readable: false,
        reason: "/root/.codex/sessions is not mounted or not readable",
        drift: 0,
      },
    ],
  });
  await expect(page.getByTestId("agent-unreadable")).toContainText(
    "Can't read Codex sessions",
  );
});

test("a continued Claude Code session is one row that says it was continued", async ({
  page,
}) => {
  await serve(page, {
    ...LIVE,
    sessions: [
      {
        ...session("completed", "observed", "omniHarness"),
        session_id: "22222222-bbbb-4bbb-8bbb-000000000002",
        agent: "claude",
        agent_label: "Claude Code",
        continued_from: "11111111-aaaa-4aaa-8aaa-000000000001",
        continued_in: null,
      },
      {
        ...session("completed", "observed", "beta-site"),
        session_id: "33333333-cccc-4ccc-8ccc-000000000003",
        continued_from: null,
        continued_in: "44444444-dddd-4ddd-8ddd-000000000004",
      },
    ],
  });
  const rows = page.getByTestId("session");
  await expect(rows).toHaveCount(2);
  await expect(rows.nth(0).getByTestId("continued")).toHaveText(
    "Continued from an earlier session · 11111111 · shown as one",
  );
  await expect(rows.nth(1).getByTestId("continued")).toHaveText(
    "Continued in another session · 44444444 · not in view",
  );
});
