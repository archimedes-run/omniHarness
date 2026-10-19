import { expect, test, type Page } from "@playwright/test";

/**
 * Phase 2.5 — a pending Tier 3 action appears as an approval card INSIDE the
 * chat thread that produced it, with Confirm and Decline calling the same
 * route as the Inbox (one implementation; the server side is confirm_flow).
 *
 * NO BACKEND: the thread is empty and the pending set is intercepted.
 */
const THREAD = "11111111-2222-3333-4444-555555555555";
const HOUR = 60 * 60 * 1000;

function action(id: string, threadId: string) {
  return {
    id,
    tool_name: "calendar_decline",
    plan_text: `I will decline 1 meeting (${id})`,
    targets: ["Standup"],
    requester: "lead_agent",
    delegation_chain: [],
    expires_at: new Date(Date.now() + 4 * HOUR).toISOString(),
    thread_id: threadId,
    threshold_targets: 10,
    requires_typed_count: false,
    withheld: false,
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
        action_id: "a-here",
        message: "Done.",
        detail: {},
      }),
    );
  });
  await page.goto(`/workspace/chats/${THREAD}`);
  return resolved;
}

test("this thread's pending action shows inside the thread, and another thread's does not", async ({
  page,
}) => {
  await openThread(page, [
    action("a-here", THREAD),
    action("a-other", "elsewhere"),
  ]);

  const cards = page.getByTestId("pending-action");
  await expect(cards).toHaveCount(1);
  await expect(cards).toContainText("a-here");
});

test("Confirm in the thread calls the same route as the Inbox", async ({
  page,
}) => {
  const resolved = await openThread(page, [action("a-here", THREAD)]);

  await page
    .getByRole("button", { name: /confirm/i })
    .first()
    .click();

  await expect.poll(() => resolved.length).toBe(1);
  expect(resolved[0]).toContain("/api/confirmations/a-here/");
});

test("a thread with nothing pending shows no card at all", async ({ page }) => {
  await openThread(page, [action("a-other", "elsewhere")]);

  await expect(page.getByTestId("pending-confirmations")).toHaveCount(0);
});
