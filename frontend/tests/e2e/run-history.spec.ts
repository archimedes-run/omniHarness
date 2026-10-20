import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

/**
 * Feature 006 run history, end to end in Settings → Activity log, against a
 * stateful fake that refuses a delete without confirm=delete-all (422), as the
 * gateway does.
 */
test("the run history is deleted only after confirming", async ({ page }) => {
  mockLangGraphAPI(page);
  const state = { runs: 5, retention: 30 };
  const json = (body: unknown, status = 200) => ({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
  await page.route("**/api/run-history/**", (route) => {
    const req = route.request();
    if (req.method() === "DELETE") {
      if (!req.url().includes("confirm=delete-all"))
        return route.fulfill(json({ detail: "needs confirm" }, 422));
      const deleted = state.runs;
      state.runs = 0;
      return route.fulfill(json({ deleted }));
    }
    if (req.method() === "PUT")
      state.retention = (
        req.postDataJSON() as { retention_days: number }
      ).retention_days;
    return route.fulfill(
      json({
        retention_days: state.retention,
        runs: state.runs,
        location: "/data/run-history",
      }),
    );
  });
  await page.route("**/api/triggers/firings", (r) =>
    r.fulfill(json({ firings: [] })),
  );

  await page.goto("/workspace/settings/activity");
  await expect(page.getByTestId("run-count")).toContainText("5 runs", {
    timeout: 15_000,
  });
  await page.getByLabel("Days to keep runs").fill("14");
  await page.getByRole("button", { name: "Save" }).click();
  await expect.poll(() => state.retention).toBe(14);

  await page.getByRole("button", { name: "Delete run history" }).click();
  expect(state.runs).toBe(5);
  await page.getByRole("button", { name: "Delete all runs" }).click();
  await expect(page.getByTestId("deleted")).toHaveText("Deleted 5 runs.");
  expect(state.runs).toBe(0);
});
