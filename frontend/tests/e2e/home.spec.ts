import { expect, test, type Page, type Route } from "@playwright/test";

import {
  MOCK_RUN_ID,
  MOCK_THREAD_ID,
  mockLangGraphAPI,
} from "./utils/mock-api";

/**
 * Home end to end (Feature 006): the New chat badge leads to Home; dismissing
 * a missed alert there is saved on the server and the badge drops, on Home
 * and on every page after; and the chat bar at the bottom of Home starts a
 * new chat and opens it.
 *
 * The gateway is stood in for by a small stateful fake: a dismissal POSTed to
 * /api/home/dismissals is what makes /api/inbox/alerts stop counting the
 * alert, as the real gateway does (backend/tests/home covers that half).
 */
const json = (route: Route, body: unknown) =>
  route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(body),
  });

async function fakeGateway(page: Page) {
  const dismissed = new Set<string>();
  const alerts = [
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
      reason: "quiet hours",
      thread_id: null,
    },
  ];
  await page.route("**/api/confirmations", (route) =>
    json(route, { actions: [], readable: true, error: "" }),
  );
  await page.route("**/api/inbox/alerts", (route) => {
    const list = alerts.map((a) => ({
      ...a,
      dismissed: dismissed.has(`${a.rule_id}:${a.event_id}`),
    }));
    return json(route, {
      alerts: list,
      waiting_count: list.filter((a) => !a.dismissed).length,
      dismissals_readable: true,
    });
  });
  await page.route("**/api/home/dismissals", (route) => {
    if (route.request().method() === "POST") {
      const body = route.request().postDataJSON() as { keys?: string[] };
      body.keys?.forEach((k) => dismissed.add(k));
    }
    return json(route, {
      alert_keys: [...dismissed],
      name_prompt_dismissed: true,
    });
  });
  await page.route("**/api/preferences", (route) =>
    json(route, {
      appearance: "system",
      appearance_chosen: false,
      display_name: "Rishabh",
      display_name_effective: "Rishabh",
    }),
  );
  return dismissed;
}

test.describe("Home", () => {
  test.beforeEach(async ({ page }) => {
    mockLangGraphAPI(page);
  });

  test("dismissing an alert on Home drops the New chat badge, here and on every page after", async ({
    page,
  }) => {
    const dismissed = await fakeGateway(page);
    await page.goto("/workspace/chats");
    const badge = page.getByTestId("inbox-badge");
    await expect(badge).toHaveText("2", { timeout: 15_000 });

    await badge.click();
    await expect(page).toHaveURL(/\/workspace\/home$/);
    await page.getByRole("button", { name: "Dismiss weekly-review" }).click();

    await expect(badge).toHaveText("1");
    expect([...dismissed]).toEqual(["weekly-review:w1"]);

    await page.goto("/workspace/chats");
    await expect(page.getByTestId("inbox-badge")).toHaveText("1", {
      timeout: 15_000,
    });
  });

  test("the chat bar at the bottom of Home starts a new chat and opens it", async ({
    page,
  }) => {
    await fakeGateway(page);
    let sent = "";
    await page.route("**/runs/stream", (route) => {
      sent = route.request().postData() ?? "";
      // As the real server answers: the new run's location in a header,
      // which is what tells the page the chat was created.
      return route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        headers: {
          "Content-Location": `/threads/${MOCK_THREAD_ID}/runs/${MOCK_RUN_ID}`,
        },
        body: `event: metadata\ndata: ${JSON.stringify({ run_id: MOCK_RUN_ID, thread_id: MOCK_THREAD_ID })}\n\nevent: end\ndata: {}\n\n`,
      });
    });
    await page.goto("/workspace/home");
    const bar = page.getByTestId("home-chat-bar");
    const textarea = bar.getByLabel("Message", { exact: true });
    await expect(textarea).toBeVisible({ timeout: 15_000 });
    await textarea.fill("Plan my week");
    await textarea.press("Enter");

    await expect(page).toHaveURL(`/workspace/chats/${MOCK_THREAD_ID}`, {
      timeout: 15_000,
    });
    expect(sent).toContain("Plan my week");
  });
});
