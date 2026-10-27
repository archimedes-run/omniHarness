import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

/**
 * The landing page ("B · Product-first"): the brand is a link in the header
 * nav, and the hero's call to action is "Get started" -> /workspace (the
 * closing section repeats it).
 */
test.describe("Landing page", () => {
  test("renders the header and hero section", async ({ page }) => {
    await page.goto("/");

    // Header brand, linking home
    await expect(
      page.locator("header").getByRole("link", { name: /OmniHarness/ }),
    ).toBeVisible();

    // The hero's heading and its call to action
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    // The hero's is the first of two (the closing section repeats it).
    await expect(
      page.getByRole("link", { name: /get started/i }).first(),
    ).toBeVisible();
  });

  test("Get started navigates to a new chat in the workspace", async ({
    page,
  }) => {
    mockLangGraphAPI(page);

    await page.goto("/");
    await page
      .getByRole("link", { name: /get started/i })
      .first()
      .click();

    // /workspace redirects to a new chat
    await page.waitForURL("**/workspace/chats/new");
    await expect(page).toHaveURL(/\/workspace\/chats\/new/);
  });
});
