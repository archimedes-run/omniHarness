import { expect, test, type Page } from "@playwright/test";

/**
 * The sidebar: New chat · Chats · Inbox · Projects (Feature 005) · Automations · Connections
 * · Agents, and More (with Settings) in the footer. The failing-source count
 * stays visible on Connections without opening anything (Feature 004 FR-041);
 * a dot on More says something inside it needs attention.
 */
const json = (body: unknown) => ({
  status: 200,
  contentType: "application/json",
  body: JSON.stringify(body),
});

const POLICY = (keptPrevious: boolean) => ({
  source_file: "rules.yaml",
  rules: [],
  unreadable: false,
  kept_previous: keptPrevious,
  error: keptPrevious ? "line 4: not a list" : null,
  threshold_targets: 10,
  expires_after_seconds: 14400,
});

async function serve(page: Page, { failing = 0, keptPrevious = false } = {}) {
  await page.route("**/api/tool-sources*", (route) =>
    route.fulfill(
      json({
        thread_id: null,
        failing,
        connectors_available: false,
        sources: [],
      }),
    ),
  );
  await page.route("**/api/policy/rules", (route) =>
    route.fulfill(json(POLICY(keptPrevious))),
  );
  await page.route("**/api/confirmations", (route) =>
    route.fulfill(json({ actions: [], readable: true, error: "" })),
  );
  await page.route("**/api/inbox/alerts", (route) =>
    route.fulfill(json({ alerts: [], waiting_count: 0 })),
  );
  await page.goto("/workspace/chats");
}

test("the sidebar reads New chat, Chats, Inbox, Projects, Automations, Connections, Agents", async ({
  page,
}) => {
  await serve(page);
  const sidebar = page.locator('[data-sidebar="sidebar"]');
  const labels = await sidebar
    .locator('[data-sidebar="menu-button"]')
    .allInnerTexts();
  const main = labels
    .map((l) => l.replace(/\s+\d+$/, "").trim())
    .filter((l) =>
      [
        "New chat",
        "Chats",
        "Inbox",
        "Projects",
        "Automations",
        "Connections",
        "Agents",
        "Settings",
      ].includes(l),
    );
  expect(main).toEqual([
    "New chat",
    "Chats",
    "Inbox",
    "Projects",
    "Automations",
    "Connections",
    "Agents",
  ]);
});

test("Settings lives in More, not on its own", async ({ page }) => {
  await serve(page);
  await expect(
    page.locator('[data-sidebar="sidebar"] a[href^="/workspace/settings"]'),
  ).toHaveCount(0);
  await page.getByRole("button", { name: /More/ }).click();
  await expect(page.getByTestId("more-settings")).toBeVisible();
  await expect(page.getByTestId("more-settings")).toHaveAttribute(
    "href",
    "/workspace/settings",
  );
});

test("a failing tool source shows on Connections without opening anything (FR-041)", async ({
  page,
}) => {
  await serve(page, { failing: 2 });
  const connections = page.locator(
    '[data-sidebar="menu-item"]:has(a[href="/workspace/connections"])',
  );
  await expect(connections.getByTestId("failing-sources")).toHaveText("2");
});

test("More carries a dot when something inside it needs attention, and only then", async ({
  page,
}) => {
  await serve(page, { keptPrevious: false });
  await expect(page.getByTestId("more-attention")).toHaveCount(0);

  await serve(page, { keptPrevious: true });
  await expect(page.getByTestId("more-attention")).toBeVisible();
});
