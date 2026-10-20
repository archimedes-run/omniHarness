import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

// Feature 006: the sidebar holds New chat · Chats · MCP Suite; Agents, Skills,
// Automations and Tasks moved to the capsule, where each opens as a panel.
test.describe("Sidebar navigation", () => {
  test("sidebar contains Chats and MCP Suite nav links", async ({ page }) => {
    mockLangGraphAPI(page);

    await page.goto("/workspace/chats/new");

    // Sidebar uses data-sidebar="menu-button" with asChild rendering on <Link>
    const sidebar = page.locator("[data-sidebar='sidebar']");
    await expect(sidebar.locator("a[href='/workspace/chats']")).toBeVisible({
      timeout: 15_000,
    });
    await expect(
      sidebar.locator("a[href='/workspace/connections']"),
    ).toBeVisible();
  });

  test("Agents in the capsule opens the Agents panel", async ({ page }) => {
    mockLangGraphAPI(page);

    await page.goto("/workspace/chats/new");

    const agents = page.locator(
      "[data-testid='capsule'] [data-capsule='agents']",
    );
    await expect(agents).toBeVisible({ timeout: 15_000 });
    await agents.click();

    await expect(page).toHaveURL(/[?&]panel=agents/);
    await expect(page.getByRole("dialog")).toBeVisible();
  });
});
