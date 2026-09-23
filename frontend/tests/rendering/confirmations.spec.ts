import { expect, test, type Page } from "@playwright/test";

/**
 * Surface 1, asserted against what a user can actually press.
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
    ...overrides,
  };
}

async function serve(page: Page, body: Record<string, unknown>) {
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
  await page.goto("/workspace/confirmations");
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
