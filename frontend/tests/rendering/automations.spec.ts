import { expect, test, type Page } from "@playwright/test";

/**
 * T060, moved with its content (Phase 2.5): the rules are on Automations, the
 * firing log on Settings → Activity log. Asserted against what renders
 * (SC-008, SC-010), plus the Automations edit path.
 *
 * NO BACKEND: the routes are intercepted. The data the real engine writes, the
 * routes' reading of it, and the write path's validation are pytest's
 * (test_production_wiring.py, test_automations_router.py).
 */

const RULE_DEFAULTS = {
  prompt: "Brief me as of {scheduled_at}.",
  destination: "auto",
  urgent: false,
};

const RULES_RAW = {
  engine_enabled: true,
  rules_error: null,
  version: "v1",
  writable: true,
  not_writable_reason: null,
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

const RULES = {
  ...RULES_RAW,
  rules: RULES_RAW.rules.map((r) => ({
    ...RULE_DEFAULTS,
    ...r,
    match: { schedule: "45 8 * * 1-5", timezone: "America/New_York" },
  })),
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

const AUTOMATIONS = "/workspace/automations";
const ACTIVITY = "/workspace/settings/activity";

async function serve(page: Page, path: string) {
  const writes: { method: string; url: string; body: unknown }[] = [];
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
  await page.route("**/api/policy/audit", (route) => route.fulfill(json([])));
  await page.route("**/api/automations/templates", (route) =>
    route.fulfill(json(TEMPLATES)),
  );
  await page.route("**/api/automations/rules**", (route) => {
    const req = route.request();
    writes.push({
      method: req.method(),
      url: req.url(),
      body: req.postDataJSON(),
    });
    const prompt = (req.postDataJSON() as { rule?: { prompt?: string } } | null)
      ?.rule?.prompt;
    if (prompt?.includes("{nonsense}")) {
      return route.fulfill({
        status: 422,
        contentType: "application/json",
        body: JSON.stringify({
          detail:
            "rule 'hushed': prompt references ['nonsense'], which a cron event cannot supply. Available: ['scheduled_at']",
        }),
      });
    }
    return route.fulfill(json({ version: "v2" }));
  });
  await page.goto(path);
  return writes;
}

const TEMPLATES = [
  {
    template: "weekly-review",
    title: "Weekly review",
    description: "Every Friday afternoon.",
    rule: {
      id: "weekly-review",
      type: "cron",
      enabled: true,
      match: { schedule: "0 16 * * 5", timezone: "America/New_York" },
      prompt: "Review my week as of {scheduled_at}.",
      destination: "auto",
    },
  },
];

test("a quiet-hours suppression differs from a delivery and from a rule that never evaluated (SC-008)", async ({
  page,
}) => {
  await serve(page, ACTIVITY);

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

  await serve(page, AUTOMATIONS);
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
  await serve(page, ACTIVITY);

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
  await serve(page, AUTOMATIONS);

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

// --- Automations: editable (Phase 2.5) ---------------------------------------

test("the toggle turns a rule off through the write path, naming the version it saw", async ({
  page,
}) => {
  const writes = await serve(page, AUTOMATIONS);

  await page.getByRole("switch", { name: "Turn off hushed" }).click();

  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0]!.method).toBe("PATCH");
  expect(writes[0]!.url).toContain("/api/automations/rules/hushed/enabled");
  expect(writes[0]!.body).toEqual({ enabled: false, version: "v1" });
});

test("an invalid edit shows the engine's reason inline, and says the rules in force are unchanged", async ({
  page,
}) => {
  await serve(page, `${AUTOMATIONS}/hushed`);

  await expect(
    page.getByRole("textbox", { name: /What to ask/ }),
  ).toBeVisible();
  await page
    .getByRole("textbox", { name: /What to ask/ })
    .fill("Hi {nonsense}");
  await page.getByRole("button", { name: "Save changes" }).click();

  const error = page.getByTestId("rule-error");
  await expect(error).toContainText("cannot supply");
  await expect(error).toContainText("rules in force have not changed");
  await expect(page.getByTestId("rule-saved")).toHaveCount(0);
});

test("the schedule is edited as time, days and zone, and saved as cron", async ({
  page,
}) => {
  const writes = await serve(page, `${AUTOMATIONS}/hushed`);

  await page.getByLabel("Time", { exact: true }).fill("07:30");
  await page.getByRole("button", { name: "Sat" }).click();
  await page.getByRole("button", { name: "Save changes" }).click();

  await expect(page.getByTestId("rule-saved")).toBeVisible();
  const body = writes[0]!.body as { rule: { match: { schedule: string } } };
  expect(writes[0]!.method).toBe("PUT");
  expect(body.rule.match.schedule).toBe("30 7 * * 1,2,3,4,5,6");
});

test("a rule's page shows that rule's history and no other", async ({
  page,
}) => {
  await serve(page, `${AUTOMATIONS}/brief-a`);

  const history = page.getByTestId("history").getByTestId("firing");
  await expect(history.first()).toBeVisible();
  for (const row of await history.all()) {
    await expect(row).toHaveAttribute("data-rule", "brief-a");
  }
});

test("a template becomes a new rule through the create route", async ({
  page,
}) => {
  const writes = await serve(page, AUTOMATIONS);

  await page.getByTestId("template").first().click();
  await page.getByRole("button", { name: "Create automation" }).click();

  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0]!.method).toBe("POST");
  expect((writes[0]!.body as { rule: { id: string } }).rule.id).toBe(
    "weekly-review",
  );
});
