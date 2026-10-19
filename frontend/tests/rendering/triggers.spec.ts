import { expect, test, type Page } from "@playwright/test";

/**
 * T060 — the triggers surface, asserted against what renders (SC-008, SC-010).
 *
 * NO BACKEND: the two routes are intercepted. The data the real engine writes,
 * and the routes' reading of it, are pytest's (test_production_wiring.py).
 */

const RULES = {
  engine_enabled: true,
  rules_error: null,
  rules: [
    {
      id: "hushed",
      type: "cron",
      enabled: true,
      match: {},
      activity: "fired",
      last_evaluated_at: "2026-10-19T23:00:00Z",
      last_evaluated: "recorded",
      last_fired_at: "2026-10-19T23:00:00Z",
      last_outcome: "suppressed",
    },
    {
      id: "brief-a",
      type: "cron",
      enabled: true,
      match: {},
      activity: "fired",
      last_evaluated_at: "2026-10-20T12:45:00Z",
      last_evaluated: "recorded",
      last_fired_at: "2026-10-20T12:45:00Z",
      last_outcome: "delivered",
    },
    {
      id: "dormant",
      type: "cron",
      enabled: true,
      match: {},
      activity: "never-evaluated",
      last_evaluated_at: null,
      last_evaluated: "never",
      last_fired_at: null,
      last_outcome: null,
    },
    {
      id: "watching",
      type: "watcher",
      enabled: true,
      match: {},
      activity: "evaluated-never-fired",
      last_evaluated_at: "2026-10-20T12:50:00Z",
      last_evaluated: "recorded",
      last_fired_at: null,
      last_outcome: null,
    },
    {
      id: "legacy",
      type: "cron",
      enabled: true,
      match: {},
      activity: "fired",
      last_evaluated_at: null,
      last_evaluated: "not-recorded",
      last_fired_at: "2026-08-01T09:00:00Z",
      last_outcome: "delivered",
    },
  ],
};

const FIRINGS = {
  firings: [
    {
      at: "2026-10-20T12:45:00Z",
      rule_id: "brief-a",
      event_type: "cron",
      event_id: "e1",
      outcome: "delivered",
      reason: "",
      batch: "batched",
      batch_id: "b1",
      delivered_with: [{ rule_id: "brief-b", event_id: "e2" }],
    },
    {
      at: "2026-10-20T12:45:00Z",
      rule_id: "brief-b",
      event_type: "cron",
      event_id: "e2",
      outcome: "delivered",
      reason: "",
      batch: "batched",
      batch_id: "b1",
      delivered_with: [{ rule_id: "brief-a", event_id: "e1" }],
    },
    {
      at: "2026-10-19T23:00:00Z",
      rule_id: "hushed",
      event_type: "cron",
      event_id: "e0",
      outcome: "suppressed",
      reason: "quiet hours 22:00-07:30",
      batch: "alone",
      batch_id: null,
      delivered_with: [],
    },
  ],
};

async function serve(page: Page) {
  const json = (body: unknown) => ({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
  await page.route("**/api/triggers/rules", (route) =>
    route.fulfill(json(RULES)),
  );
  await page.route("**/api/triggers/firings", (route) =>
    route.fulfill(json(FIRINGS)),
  );
  await page.goto("/workspace/triggers");
}

test("a quiet-hours suppression differs from a delivery and from a rule that never evaluated (SC-008)", async ({
  page,
}) => {
  await serve(page);

  const suppressed = page.locator(
    '[data-testid="firing"][data-outcome="suppressed"]',
  );
  const delivered = page
    .locator('[data-testid="firing"][data-outcome="delivered"]')
    .first();
  // Distinct in what is DRAWN — the icon and the badge — not only in an
  // attribute derived from the outcome string.
  const iconOf = (row: typeof suppressed) =>
    row.getByTestId("outcome-icon").getAttribute("class");
  expect(await iconOf(suppressed)).not.toBe(await iconOf(delivered));
  await expect(suppressed).toContainText("Suppressed");
  await expect(delivered).toContainText("Delivered");
  // The reason as recorded, not a status word (FR-019).
  await expect(suppressed.getByTestId("reason")).toHaveText(
    "quiet hours 22:00-07:30",
  );

  const never = page.locator('[data-testid="rule"][data-rule="dormant"]');
  const evaluating = page.locator('[data-testid="rule"][data-rule="watching"]');
  await expect(never).toContainText("Never evaluated");
  await expect(evaluating).toContainText("Evaluating, never fired");
  await expect(never.getByTestId("activity-icon")).toHaveAttribute(
    "aria-label",
    "never-evaluated",
  );
});

test("firings coalesced into one message each name the others (SC-010)", async ({
  page,
}) => {
  await serve(page);

  await expect(
    page
      .locator('[data-testid="firing"][data-rule="brief-a"]')
      .getByTestId("delivered-with"),
  ).toContainText("brief-b");
  await expect(
    page
      .locator('[data-testid="firing"][data-rule="brief-b"]')
      .getByTestId("delivered-with"),
  ).toContainText("brief-a");
});

test("a time that was not recorded is not shown as never (FR-022)", async ({
  page,
}) => {
  await serve(page);

  await expect(
    page
      .locator('[data-testid="rule"][data-rule="legacy"]')
      .getByTestId("last-evaluated"),
  ).toHaveText("not recorded");
  await expect(
    page
      .locator('[data-testid="rule"][data-rule="dormant"]')
      .getByTestId("last-evaluated"),
  ).toHaveText("never");
});
