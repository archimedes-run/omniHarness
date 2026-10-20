import { expect, test, type Page } from "@playwright/test";

/**
 * The Inbox (Phase 2.5; Feature 004's Surface 1 moved here with its content),
 * now the interim Home (Feature 006): /workspace/inbox redirects there,
 * asserted against what a user can actually press.
 *
 * The unit tests cover the countdown and threshold LOGIC. They cannot tell you
 * whether the Confirm button is disabled — that is a property of the render,
 * and the gap between "the rule is right" and "the control obeys it" is the
 * one that let a broken dark theme ship with a green suite.
 *
 * NO BACKEND. The page is served with OMNI_HARNESS_AUTH_DISABLED=1 and the
 * pending list is supplied by intercepting the API, so this asserts the UI
 * given a server response. The server's own behaviour — the claim, the seven
 * outcomes, the unreadable-store distinction — is covered in pytest, where it
 * belongs.
 */

const HOUR = 60 * 60 * 1000;

function action(overrides: Record<string, unknown> = {}) {
  return {
    id: "abc123abc123",
    tool_name: "calendar_decline",
    plan_text: "I will decline 2 meetings: Standup, Review",
    targets: ["Standup", "Review"],
    requester: "lead_agent",
    delegation_chain: [],
    expires_at: new Date(Date.now() + 4 * HOUR).toISOString(),
    thread_id: "t1",
    threshold_targets: 10,
    requires_typed_count: false,
    withheld: false,
    ...overrides,
  };
}

const NO_ALERTS = { alerts: [], waiting_count: 0 };

async function serve(
  page: Page,
  body: Record<string, unknown>,
  alerts: Record<string, unknown> = NO_ALERTS,
) {
  await page.route("**/api/inbox/alerts", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(alerts),
    }),
  );
  await page.route("**/api/confirmations", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(body),
    });
  });
  let resolveCalls = 0;
  await page.route("**/api/confirmations/*/**", async (route) => {
    resolveCalls += 1;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        outcome: "executed",
        action_id: "abc123abc123",
        message: "Done.",
        detail: {},
      }),
    });
  });
  await page.goto("/workspace/home");
  return () => resolveCalls;
}

test("POSITIVE CONTROL: a pending action renders with its plan and targets", async ({
  page,
}) => {
  // Without this, every "the button is disabled" assertion below would also
  // pass on a page that rendered nothing at all.
  await serve(page, { actions: [action()], readable: true, error: "" });

  await expect(page.getByTestId("pending-action")).toBeVisible();
  await expect(page.getByTestId("targets")).toContainText("Standup");
  await expect(page.getByTestId("confirm")).toBeEnabled();
});

test("an above-threshold action cannot be confirmed by clicking", async ({
  page,
}) => {
  const calls = await serve(page, {
    actions: [
      action({
        targets: Array.from({ length: 14 }, (_, i) => `Meeting ${i}`),
        requires_typed_count: true,
      }),
    ],
    readable: true,
    error: "",
  });

  await expect(page.getByTestId("typed-count")).toBeVisible();
  await expect(page.getByTestId("confirm")).toBeDisabled();
  expect(calls(), "a disabled control still reached the server").toBe(0);
});

test("a wrong typed count neither confirms nor resolves", async ({ page }) => {
  const calls = await serve(page, {
    actions: [
      action({
        targets: Array.from({ length: 14 }, (_, i) => `Meeting ${i}`),
        requires_typed_count: true,
      }),
    ],
    readable: true,
    error: "",
  });

  await page.getByTestId("typed-count").fill("13");
  await expect(page.getByTestId("confirm")).toBeDisabled();

  await page.getByTestId("typed-count").fill("14");
  await expect(page.getByTestId("confirm")).toBeEnabled();
  expect(calls()).toBe(0);
});

test("an expired action's controls are inoperable, not merely ignored", async ({
  page,
}) => {
  await serve(page, {
    actions: [
      action({ expires_at: new Date(Date.now() - HOUR).toISOString() }),
    ],
    readable: true,
    error: "",
  });

  await expect(page.getByTestId("remaining")).toHaveText("expired");
  await expect(page.getByTestId("confirm")).toBeDisabled();
  await expect(page.getByTestId("decline")).toBeDisabled();
});

test("an action expiring while displayed becomes expired without a reload", async ({
  page,
}) => {
  // FR-005. Two seconds out, then watch the page do it on its own.
  await serve(page, {
    actions: [
      action({ expires_at: new Date(Date.now() + 2000).toISOString() }),
    ],
    readable: true,
    error: "",
  });

  await expect(page.getByTestId("confirm")).toBeEnabled();
  await expect(page.getByTestId("remaining")).toHaveText("expired", {
    timeout: 10_000,
  });
  await expect(page.getByTestId("confirm")).toBeDisabled();
});

test("declining stays available where confirming is blocked", async ({
  page,
}) => {
  await serve(page, {
    actions: [
      action({
        targets: Array.from({ length: 14 }, (_, i) => `Meeting ${i}`),
        requires_typed_count: true,
      }),
    ],
    readable: true,
    error: "",
  });

  await expect(page.getByTestId("confirm")).toBeDisabled();
  await expect(page.getByTestId("decline")).toBeEnabled();
});

test("an unreadable pending set is not rendered as an empty one", async ({
  page,
}) => {
  await serve(page, {
    actions: [],
    readable: false,
    error: "permission denied",
  });

  await expect(page.getByTestId("unreadable")).toBeVisible();
  await expect(page.getByTestId("empty")).toHaveCount(0);
});

test("an empty pending set says so plainly", async ({ page }) => {
  await serve(page, { actions: [], readable: true, error: "" });

  await expect(page.getByTestId("empty")).toBeVisible();
  await expect(page.getByTestId("unreadable")).toHaveCount(0);
});

test("a plan that failed redaction shows as withheld, not as the plan (FR-031, SC-015)", async ({
  page,
}) => {
  await serve(page, {
    actions: [
      action({
        plan_text:
          "Withheld: this could not be safely redacted for display. Check it locally.",
        withheld: true,
      }),
    ],
    readable: true,
    error: "",
  });

  await expect(page.getByTestId("withheld")).toBeVisible();
  await expect(page.getByTestId("withheld")).toContainText("Withheld");
});

// --- alerts, and the badge (Phase 2.5) ----------------------------------------

const ALERTS = {
  alerts: [
    {
      rule_id: "blocked-session",
      event_id: "s1",
      event_type: "watcher",
      at: new Date().toISOString(),
      state: "waiting",
      reason: "awaiting the coalescing window",
      thread_id: "t-blocked",
    },
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
      rule_id: "morning-briefing",
      event_id: "m1",
      event_type: "cron",
      at: new Date().toISOString(),
      state: "delivered",
      reason: "",
      thread_id: "t-morning",
    },
  ],
  waiting_count: 2,
};

test("alerts say whether they are waiting, missed or delivered, and link to their conversation", async ({
  page,
}) => {
  await serve(page, { actions: [], readable: true, error: "" }, ALERTS);

  await expect(
    page.getByTestId("alerts-waiting").getByTestId("alert"),
  ).toHaveCount(2);
  // Feature 006: Home shows only what is waiting or missed; the delivered
  // one is history, in the Activity log.
  await expect(page.getByTestId("alerts-recent")).toHaveCount(0);
  await expect(
    page.locator('[data-testid="alert"][data-state="not-delivered"]'),
  ).toContainText("held past 2h");
  await expect(
    page.locator('[data-testid="alert"][data-state="waiting"] a'),
  ).toHaveAttribute("href", "/workspace/chats/t-blocked");

  await page.route("**/api/triggers/firings", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ firings: [] }),
    }),
  );
  await page.goto("/workspace/settings/activity");
  const history = page.getByTestId("alerts-recent").getByTestId("alert");
  await expect(history).toHaveCount(1);
  await expect(history).toHaveAttribute("data-state", "delivered");
});

test("the waiting badge counts confirmations plus waiting alerts", async ({
  page,
}) => {
  await serve(page, { actions: [action()], readable: true, error: "" }, ALERTS);

  await expect(page.getByTestId("inbox-badge")).toHaveText("3");
});

test("the badge says it cannot tell, rather than showing 0, when the pending set is unreadable", async ({
  page,
}) => {
  await serve(
    page,
    { actions: [], readable: false, error: "store unreadable" },
    NO_ALERTS,
  );

  await expect(page.getByTestId("inbox-badge")).toHaveAttribute(
    "data-count",
    "unknown",
  );
});

test("nothing waiting shows no badge at all", async ({ page }) => {
  await serve(page, { actions: [], readable: true, error: "" }, NO_ALERTS);

  await expect(page.getByTestId("empty")).toBeVisible();
  await expect(page.getByTestId("inbox-badge")).toHaveCount(0);
});

test("/workspace/inbox (and the old /workspace/confirmations) land on Home", async ({
  page,
}) => {
  await serve(page, { actions: [action()], readable: true, error: "" });
  for (const old of ["/workspace/inbox", "/workspace/confirmations"]) {
    await page.goto(old);
    await expect(page).toHaveURL(/\/workspace\/home$/);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Home");
    await expect(
      page.getByRole("heading", { name: "Waiting on you" }),
    ).toBeVisible();
    await expect(page.getByTestId("pending-action")).toBeVisible();
  }
});
