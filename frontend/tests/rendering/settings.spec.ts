import { expect, test, type Page } from "@playwright/test";

/**
 * Settings (Feature 006 board "Settings"): the section column in the board's
 * order, Memory's Summary / Facts tabs, and Safety holding the tool sources
 * and the policy that moved there (their old URLs redirect).
 */
const json = (body: unknown) => ({
  status: 200,
  contentType: "application/json",
  body: JSON.stringify(body),
});
const SOURCES = {
  thread_id: null,
  failing: 1,
  connectors_available: true,
  sources: [
    {
      id: "local:session-watcher",
      name: "session-watcher",
      kind: "local",
      state: "unreachable",
      tool_count: null,
      error: "connection refused · host.docker.internal:18101",
      selected: null,
      last_success_at: null,
      last_failure_at: null,
    },
    {
      id: "connector:GMAIL",
      name: "Gmail",
      kind: "connector",
      state: "authorised",
      tool_count: null,
      error: null,
      selected: null,
      last_success_at: new Date(Date.now() - 3_600_000).toISOString(),
      last_failure_at: null,
    },
  ],
};

async function stub(page: Page) {
  await page.route("**/api/tool-sources*", (r) => r.fulfill(json(SOURCES)));
  await page.route("**/api/policy/rules", (r) =>
    r.fulfill(
      json({
        source_file: "rules.yaml",
        rules: [
          { pattern: "gmail_fetch_*", tier: 1, exceptions: [], source_line: 1 },
        ],
        unreadable: false,
        kept_previous: false,
        error: null,
        threshold_targets: 10,
        expires_after_seconds: 14400,
      }),
    ),
  );
  await page.route("**/api/memory", (r) =>
    r.fulfill(
      json({
        version: "1.0",
        lastUpdated: new Date().toISOString(),
        user: {
          workContext: { summary: "Builds OmniHarness.", updatedAt: "" },
          personalContext: { summary: "", updatedAt: "" },
          topOfMind: { summary: "", updatedAt: "" },
        },
        history: {
          recentMonths: { summary: "", updatedAt: "" },
          earlierContext: { summary: "", updatedAt: "" },
          longTermBackground: { summary: "", updatedAt: "" },
        },
        facts: [
          {
            id: "f1",
            content: "Prefers tables",
            category: "preference",
            confidence: 0.9,
            createdAt: new Date().toISOString(),
            source: "t1",
          },
        ],
      }),
    ),
  );
}

test("the section column reads as the board, the open one marked", async ({
  page,
}) => {
  await stub(page);
  await page.goto("/workspace/settings/memory");
  const nav = page.getByRole("navigation", { name: "Settings" });
  await expect(nav.getByRole("link")).toHaveText([
    "Account",
    "Memory",
    "Safety",
    "Notifications",
    "Activity log",
    "Appearance",
    "About",
  ]);
  await expect(nav.getByRole("link", { name: "Memory" })).toHaveAttribute(
    "aria-current",
    "page",
  );
});

test("Memory: a 24 px title, then Summary and Facts as a real tablist", async ({
  page,
}) => {
  await stub(page);
  await page.goto("/workspace/settings/memory");
  const h1 = page.getByRole("heading", { level: 1, name: "Memory" });
  await expect(h1).toBeVisible();
  expect(await h1.evaluate((el) => getComputedStyle(el).fontSize)).toBe("24px");
  const tabs = page.getByRole("tablist", { name: "Memory views" });
  await expect(tabs.getByRole("tab")).toHaveText(["Summary", "Facts· 1"]);
  await tabs.getByRole("tab", { name: "Summary" }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(tabs.getByRole("tab", { name: /Facts/ })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await expect(page).toHaveURL(/tab=facts/);
});

test("Safety lists the tool sources, with a failing one's real error", async ({
  page,
}) => {
  await stub(page);
  await page.goto("/workspace/settings/safety");
  const sources = page.getByTestId("safety-tool-sources");
  const watcher = sources.locator('[data-source="local:session-watcher"]');
  await expect(watcher).toContainText("Unreachable");
  await expect(watcher.getByTestId("safety-source-error")).toHaveText(
    "connection refused · host.docker.internal:18101",
  );
  await expect(watcher).toContainText("No call seen yet");
  const gmail = sources.locator('[data-source="connector:GMAIL"]');
  await expect(gmail.getByRole("img", { name: "Gmail logo" })).toBeVisible();
  await expect(gmail).toContainText("(observed)");
  // And the policy, below.
  await expect(page.getByTestId("rule")).toContainText("gmail_fetch_*");
});

for (const old of ["/workspace/tool-sources", "/workspace/policy"]) {
  test(`${old} redirects to Settings > Safety`, async ({ page }) => {
    await stub(page);
    await page.goto(old);
    await expect(page).toHaveURL(/\/workspace\/settings\/safety$/);
  });
}

test("Settings opens on its first section", async ({ page }) => {
  await stub(page);
  await page.goto("/workspace/settings");
  await expect(page).toHaveURL(/\/workspace\/settings\/account$/);
  await expect(
    page.getByRole("heading", { level: 1, name: "Account" }),
  ).toBeVisible();
});
