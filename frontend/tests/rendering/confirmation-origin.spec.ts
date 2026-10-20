import { expect, test, type Page } from "@playwright/test";

/**
 * FR-006, global: an action suggested by content the assistant READ (a page,
 * an email, any tool output) is labelled with its source on its card, and only
 * the card's button can confirm it. The user's own request carries no label.
 *
 * NO BACKEND: the thread is empty and the pending set is intercepted.
 */
const THREAD = "11111111-2222-3333-4444-555555555555";
const HOUR = 60 * 60 * 1000;

function action(id: string, origin: Record<string, unknown>) {
  return {
    id,
    tool_name: "calendar_decline",
    plan_text: `I will decline 1 meeting (${id})`,
    targets: ["Standup"],
    requester: "lead_agent",
    delegation_chain: [],
    expires_at: new Date(Date.now() + 4 * HOUR).toISOString(),
    thread_id: THREAD,
    threshold_targets: 10,
    requires_typed_count: false,
    withheld: false,
    ...origin,
  };
}

async function openThread(page: Page, actions: unknown[]) {
  const json = (body: unknown) => ({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
  const resolved: string[] = [];
  await page.route("**/api/langgraph/**", (route) => {
    const url = route.request().url();
    if (url.includes("/history")) return route.fulfill(json([]));
    if (url.includes("/runs")) return route.fulfill(json([]));
    if (url.includes("/threads/search")) return route.fulfill(json([]));
    return route.fulfill(
      json({ thread_id: THREAD, values: { messages: [] }, metadata: {} }),
    );
  });
  await page.route("**/api/inbox/alerts", (route) =>
    route.fulfill(json({ alerts: [], waiting_count: 0 })),
  );
  await page.route("**/api/confirmations", (route) =>
    route.fulfill(json({ actions, readable: true, error: "" })),
  );
  await page.route("**/api/confirmations/*/**", (route) => {
    resolved.push(route.request().url());
    return route.fulfill(
      json({
        outcome: "executed",
        action_id: "x",
        message: "Done.",
        detail: {},
      }),
    );
  });
  await page.goto(`/workspace/chats/${THREAD}`);
  return resolved;
}

test("a page-suggested action names its source, and its Confirm button still works", async ({
  page,
}) => {
  const resolved = await openThread(page, [
    action("a-page", {
      origin: "content",
      origin_source: "web_fetch",
      origin_label: "Suggested by content from web_fetch",
      confirmable_by_typing: false,
    }),
  ]);

  const label = page.getByTestId("origin-label");
  await expect(label).toBeVisible();
  await expect(label).toContainText("Suggested by content from web_fetch");
  await expect(label).toContainText("Only the Confirm button here");

  await page.getByTestId("confirm").click();
  await expect.poll(() => resolved.length).toBe(1);
  expect(resolved[0]).toContain("/api/confirmations/a-page/confirm");
});

test("an automation's suggestion says so", async ({ page }) => {
  await openThread(page, [
    action("a-auto", {
      origin: "automation",
      origin_label: "Suggested by an automation",
      confirmable_by_typing: false,
    }),
  ]);

  await expect(page.getByTestId("origin-label")).toContainText(
    "Suggested by an automation",
  );
});

test("the user's own request carries no label", async ({ page }) => {
  await openThread(page, [
    action("a-user", { origin: "user", confirmable_by_typing: true }),
  ]);

  await expect(page.getByTestId("pending-action")).toHaveCount(1);
  await expect(page.getByTestId("origin-label")).toHaveCount(0);
});
