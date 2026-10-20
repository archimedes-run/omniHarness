import { expect, test, type Page } from "@playwright/test";

/**
 * The interim Home (Feature 006 Phase 1): Waiting on you (approvals and
 * coding sessions waiting on you) and While you were away (alerts not yet
 * delivered or missed, dismissable). The delivered history is in Settings →
 * Activity log (inbox.spec.ts covers that move).
 */
const json = (body: unknown, status = 200) => ({
  status,
  contentType: "application/json",
  body: JSON.stringify(body),
});

const session = (id: string, state: string) => ({
  session_id: id,
  project: `repo-${id}`,
  display_state: state,
  epistemic: state === "waiting-on-user" ? "inferred" : "observed",
  last_activity_at: new Date().toISOString(),
  quiet_seconds: 30,
  summary: `Summary of ${id}`,
  summary_provenance: "reported",
  relay_suppressed: false,
  withheld: false,
  agent: "codex",
  agent_label: "Codex",
});

const LIVE = {
  reachable: true,
  unreachable_kind: null,
  unreachable_detail: null,
  observability: "live",
  staleness_seconds: 2,
  as_of: new Date().toISOString(),
  sessions: [session("s1", "waiting-on-user"), session("s2", "working")],
  observe_only: true,
  observe_only_reason: "",
};

const ALERTS = {
  alerts: [
    {
      rule_id: "weekly-review",
      event_id: "w1",
      event_type: "cron",
      at: new Date().toISOString(),
      state: "not-delivered",
      reason: "held past 2h",
      thread_id: null,
    },
    {
      rule_id: "blocked-session",
      event_id: "b1",
      event_type: "watcher",
      at: new Date().toISOString(),
      state: "waiting",
      reason: "awaiting the coalescing window",
      thread_id: null,
    },
    {
      rule_id: "morning-briefing",
      event_id: "m1",
      event_type: "cron",
      at: new Date().toISOString(),
      state: "delivered",
      reason: "",
      thread_id: null,
    },
  ],
  waiting_count: 2,
};

async function serve(page: Page, sessions: unknown = LIVE) {
  await page.route("**/api/confirmations", (route) =>
    route.fulfill(json({ actions: [], readable: true, error: "" })),
  );
  await page.route("**/api/inbox/alerts", (route) =>
    route.fulfill(json(ALERTS)),
  );
  await page.route("**/api/sessions", (route) =>
    sessions === "error"
      ? route.fulfill(json({ detail: "boom" }, 500))
      : route.fulfill(json(sessions)),
  );
  await page.goto("/workspace/home");
}

test("Waiting on you lists the sessions waiting on you, and only those", async ({
  page,
}) => {
  await serve(page);
  const waiting = page.getByTestId("sessions-waiting");
  await expect(waiting.getByTestId("session")).toHaveCount(1);
  await expect(waiting.getByTestId("session")).toHaveAttribute(
    "data-state",
    "waiting-on-user",
  );
  await expect(waiting.getByTestId("session")).toContainText("repo-s1");
});

test("a watcher it cannot reach is 'cannot tell', not 'none waiting'", async ({
  page,
}) => {
  await serve(page, {
    ...LIVE,
    reachable: false,
    unreachable_kind: "unreachable",
    observability: null,
    sessions: null,
  });
  await expect(page.getByTestId("sessions-unreadable")).toBeVisible();
  await expect(page.getByTestId("no-sessions-waiting")).toHaveCount(0);
});

test("While you were away shows missed and unsent alerts, not delivered ones; a dismissal survives a reload", async ({
  page,
}) => {
  await serve(page);
  const away = page.getByTestId("alerts-waiting").getByTestId("alert");
  await expect(away).toHaveCount(2);
  await expect(
    page.locator('[data-testid="alert"][data-state="delivered"]'),
  ).toHaveCount(0);

  await page.getByRole("button", { name: "Dismiss weekly-review" }).click();
  await expect(away).toHaveCount(1);
  await page.reload();
  await expect(
    page.getByTestId("alerts-waiting").getByTestId("alert"),
  ).toHaveCount(1);
  await expect(
    page.locator('[data-testid="alert"][data-state="not-delivered"]'),
  ).toHaveCount(0);

  await page.getByRole("button", { name: "Dismiss blocked-session" }).click();
  await expect(page.getByTestId("no-alerts")).toBeVisible();
  // It says where a dismissal lives.
  await expect(page.getByText("in this browser only")).toBeVisible();
});
