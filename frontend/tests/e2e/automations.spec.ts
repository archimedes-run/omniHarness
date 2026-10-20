import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

/**
 * Feature 006, Automations panel, end to end through the capsule: create an
 * automation from scratch and see it in the list; edit a trigger and see the
 * saved schedule. The API is a small stateful fake of the gateway's rule file:
 * reads are /api/triggers/rules, writes the /api/automations routes, and a
 * write naming a stale version is refused (409) as the real store refuses it.
 */
type Rule = {
  id: string;
  name?: string;
  type: string;
  enabled: boolean;
  match: Record<string, unknown>;
  prompt: string;
  destination: string;
  urgent?: boolean;
};

function fakeGateway(page: Page) {
  const state = {
    version: 1,
    rules: [
      {
        id: "morning-brief",
        name: "Morning brief",
        type: "cron",
        enabled: true,
        match: { schedule: "45 8 * * 1-5", timezone: "America/New_York" },
        prompt: "Brief me as of {scheduled_at}.",
        destination: "auto",
        urgent: false,
      },
    ] as Rule[],
    writes: [] as { method: string; body: unknown }[],
  };
  const json = (body: unknown, status = 200) => ({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
  const view = () => ({
    engine_enabled: true,
    rules_error: null,
    version: `v${state.version}`,
    writable: true,
    not_writable_reason: null,
    quiet_hours: {
      enabled: true,
      start: "22:00",
      end: "07:00",
      timezone: "America/New_York",
    },
    rules: state.rules.map((r) => ({
      urgent: false,
      ...r,
      activity: "never-evaluated",
      last_evaluated_at: null,
      last_evaluated: "never",
      last_fired_at: null,
      last_outcome: null,
      next_run: r.type === "cron" ? "scheduled" : "on-event",
      next_run_at: r.type === "cron" ? "2030-01-07T08:45:00-05:00" : null,
    })),
  });
  void page.route("**/api/triggers/rules", (route) =>
    route.fulfill(json(view())),
  );
  void page.route("**/api/triggers/rules/*/runs", (route) =>
    route.fulfill(json({ rule_id: "x", runs: [] })),
  );
  void page.route("**/api/automations/templates", (route) =>
    route.fulfill(json([])),
  );
  void page.route("**/api/automations/rules**", (route) => {
    const req = route.request();
    const body = req.postDataJSON() as { rule: Rule; version: string };
    state.writes.push({ method: req.method(), body });
    if (body.version !== `v${state.version}`) {
      return route.fulfill(
        json(
          { detail: "The rules file changed since this page loaded it." },
          409,
        ),
      );
    }
    if (req.method() === "POST") {
      if (state.rules.some((r) => r.id === body.rule.id))
        return route.fulfill(json({ detail: "already exists" }, 409));
      state.rules.push(body.rule);
    } else if (req.method() === "PUT") {
      state.rules = state.rules.map((r) =>
        r.id === body.rule.id ? body.rule : r,
      );
    }
    state.version += 1;
    return route.fulfill(json({ version: `v${state.version}` }, 201));
  });
  return state;
}

async function openPanel(page: Page) {
  await page.goto("/workspace/chats/new");
  const capsule = page.locator(
    "[data-testid='capsule'] [data-capsule='automations']",
  );
  await expect(capsule).toBeVisible({ timeout: 15_000 });
  await capsule.click();
  const sheet = page.getByTestId("panel-sheet");
  await expect(sheet).toHaveAttribute("data-panel", "automations");
  return sheet;
}

test("a new automation created from scratch appears in the list", async ({
  page,
}) => {
  mockLangGraphAPI(page);
  const gateway = fakeGateway(page);
  const sheet = await openPanel(page);

  await sheet.getByTestId("new-automation").click();
  const editor = sheet.getByTestId("new-automation-editor");
  await editor.getByTestId("rule-name").fill("Standup nudge");
  await editor.getByLabel("Time", { exact: true }).fill("09:55");
  await editor.getByLabel("Time zone").fill("Europe/London");
  await editor.getByTestId("rule-prompt").fill("Standup in five minutes.");
  await editor.getByRole("button", { name: "Create automation" }).click();

  const created = sheet.locator(
    '[data-testid="rule"][data-rule="standup-nudge"]',
  );
  await expect(created).toContainText("Standup nudge");
  await expect(created).toContainText("Weekdays 9:55 AM");
  await expect(created).toHaveAttribute("aria-current", "true");
  await expect(
    sheet.getByRole("heading", { name: "Standup nudge" }),
  ).toBeVisible();
  expect(gateway.writes.map((w) => w.method)).toEqual(["POST"]);
});

test("editing a trigger saves it, and the list shows the saved schedule", async ({
  page,
}) => {
  mockLangGraphAPI(page);
  const gateway = fakeGateway(page);
  const sheet = await openPanel(page);

  await sheet.getByRole("tab", { name: "Edit" }).click();
  await sheet.getByLabel("Time", { exact: true }).fill("07:30");
  await sheet.getByRole("button", { name: "Save changes" }).click();

  await expect(sheet.getByTestId("rule-saved")).toBeVisible();
  await expect(
    sheet.locator('[data-testid="rule"][data-rule="morning-brief"]'),
  ).toContainText("Weekdays 7:30 AM");
  expect(gateway.rules[0]!.match.schedule).toBe("30 7 * * 1-5");

  // A second save from the same form names the NEW version, so it is not
  // refused as stale.
  await sheet.getByRole("button", { name: "Sun" }).click();
  await sheet.getByRole("button", { name: "Save changes" }).click();
  await expect
    .poll(() => gateway.rules[0]!.match.schedule)
    .toBe("30 7 * * 0,1,2,3,4,5");
  await expect(sheet.getByTestId("rule-error")).toHaveCount(0);
});
