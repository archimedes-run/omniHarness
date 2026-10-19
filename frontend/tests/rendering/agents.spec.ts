import { expect, test } from "@playwright/test";

/**
 * Phase 2.5 — the Agents page on a 403 "agents API disabled".
 *
 * It used to retry three times with backoff (the library default) and then
 * show the "no agents yet" empty state: slow, and wrong — switched off is not
 * the same as none.
 */
test("a disabled agents API says so, after one request, not 'no agents'", async ({
  page,
}) => {
  let calls = 0;
  await page.route("**/api/agents", (route) => {
    calls += 1;
    return route.fulfill({
      status: 403,
      contentType: "application/json",
      body: JSON.stringify({
        detail:
          "Custom-agent management API is disabled. Set agents_api.enabled=true to expose agent and user-profile routes over HTTP.",
      }),
    });
  });
  await page.goto("/workspace/agents");

  await expect(page.getByTestId("agents-disabled")).toBeVisible({
    timeout: 1500,
  });
  await expect(page.getByText("No custom agents yet")).toHaveCount(0);
  expect(calls).toBe(1);
});
