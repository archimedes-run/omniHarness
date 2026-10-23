import { expect, test, type Page } from "@playwright/test";

/**
 * Feature 006 run history, Settings → Activity log: how long runs are kept,
 * and deleting all of them behind a confirmation. NO BACKEND: the routes'
 * behaviour (redaction, purge, confirm=delete-all) is pytest's, through
 * create_app() (tests/run_history).
 */
async function serve(
  page: Page,
  opts: { warning?: string; failed?: string[] } = {},
) {
  const calls: { method: string; url: string; body: unknown }[] = [];
  let runs = 12;
  const json = (body: unknown) => ({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
  await page.route("**/api/run-history/**", (route) => {
    const req = route.request();
    calls.push({
      method: req.method(),
      url: req.url(),
      body: req.postDataJSON(),
    });
    if (req.method() === "DELETE") {
      const deleted = runs;
      runs = 0;
      return route.fulfill(
        json({
          deleted,
          threads_deleted: 2,
          threads_failed: opts.failed ?? [],
        }),
      );
    }
    const days =
      req.method() === "PUT"
        ? (req.postDataJSON() as { retention_days: number }).retention_days
        : 30;
    return route.fulfill(
      json({
        retention_days: days,
        runs,
        location: "/app/backend/.omni-harness/run-history",
        warning: opts.warning ?? null,
      }),
    );
  });
  await page.route("**/api/triggers/firings", (r) =>
    r.fulfill(json({ firings: [] })),
  );
  await page.route("**/api/inbox/alerts", (r) =>
    r.fulfill(json({ alerts: [] })),
  );
  await page.goto("/workspace/settings/activity");
  await expect(page.getByTestId("run-count")).toContainText("12 runs");
  return calls;
}

test("retention is shown and saved", async ({ page }) => {
  const calls = await serve(page);
  const days = page.getByLabel("Days to keep runs");
  await expect(days).toHaveValue("30");
  await days.fill("7");
  await page.getByRole("button", { name: "Save" }).click();
  await expect
    .poll(() => calls.find((c) => c.method === "PUT")?.body)
    .toEqual({ retention_days: 7 });
});

test("deleting the run history asks first; Keep it deletes nothing", async ({
  page,
}) => {
  const calls = await serve(page);
  await page.getByRole("button", { name: "Delete run history" }).click();
  const dialog = page.getByRole("dialog", { name: "Delete the run history?" });
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Keep it" }).click();
  await expect(dialog).toHaveCount(0);
  await page.getByRole("button", { name: "Delete run history" }).click();
  await page.keyboard.press("Escape");
  expect(calls.some((c) => c.method === "DELETE")).toBe(false);
  await expect(
    page.getByRole("button", { name: "Delete run history" }),
  ).toBeFocused();
});

test("confirming deletes every run, naming the confirmation", async ({
  page,
}) => {
  const calls = await serve(page);
  await page.getByRole("button", { name: "Delete run history" }).click();
  await page.getByRole("button", { name: "Delete runs and threads" }).click();
  await expect(page.getByTestId("deleted")).toHaveText(
    "Deleted 12 runs and 2 automation threads.",
  );
  const del = calls.find((c) => c.method === "DELETE")!;
  expect(del.url).toContain("/api/run-history/runs?confirm=delete-all");
  await expect(page.getByTestId("run-count")).toContainText("0 runs");
});

test("the dialog says exactly what is deleted and what is kept", async ({
  page,
}) => {
  await serve(page);
  await page.getByRole("button", { name: "Delete run history" }).click();
  const dialog = page.getByRole("dialog", { name: "Delete the run history?" });
  await expect(dialog.getByTestId("deletes")).toContainText(
    "Each automation's conversation thread",
  );
  await expect(dialog.getByTestId("deletes")).toContainText(
    "including anything you wrote in that thread yourself",
  );
  await expect(dialog.getByTestId("keeps")).toContainText(
    "Messages still waiting to be delivered",
  );
  await expect(dialog.getByTestId("keeps")).toContainText("Your other chats.");
});

test("a thread that could not be deleted is named", async ({ page }) => {
  await serve(page, { failed: ["thread-abc"] });
  await page.getByRole("button", { name: "Delete run history" }).click();
  await page.getByRole("button", { name: "Delete runs and threads" }).click();
  await expect(page.getByTestId("threads-failed")).toContainText(
    "1 automation thread could not be deleted and still holds its content",
  );
  await expect(page.getByTestId("threads-failed")).toContainText("thread-abc");
});

test("the size cap warning is shown", async ({ page }) => {
  await serve(page, {
    warning: "The run history is at 93% of its 512 MB cap.",
  });
  await expect(page.getByTestId("run-history-warning")).toContainText(
    "93% of its 512 MB cap",
  );
});

test("retention says it covers the automations' conversations", async ({
  page,
}) => {
  await serve(page);
  await expect(page.getByTestId("run-history-settings")).toContainText(
    "the automation starts a fresh conversation (forgetting earlier runs)",
  );
  await expect(page.getByTestId("run-history-settings")).toContainText(
    "it is kept, with only the content older than the retention removed",
  );
});
