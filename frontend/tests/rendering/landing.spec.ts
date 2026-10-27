import { expect, test } from "@playwright/test";

/**
 * The landing page in a real browser: each header anchor lands on its
 * section, the phone layout has a working menu and no sideways scroll, and
 * the page paints the theme's own background (the old hero painted a fixed
 * white glow and fade over the dark theme).
 */
const ANCHORS = [
  ["Product", "product"],
  ["A day with it", "day"],
  ["Safety", "safety"],
] as const;

test.describe("desktop", () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  for (const [label, id] of ANCHORS) {
    test(`"${label}" scrolls to #${id}`, async ({ page }) => {
      await page.goto("/");
      await page
        .getByRole("navigation", { name: "Main" })
        .getByRole("link", { name: label, exact: true })
        .click();
      await expect(page).toHaveURL(new RegExp(`/#${id}$`));
      const section = page.locator(`section#${id}`);
      await expect(section).toBeInViewport();
      // The sticky header does not cover the section's heading.
      const top = await section.evaluate(
        (el) => el.getBoundingClientRect().top,
      );
      const header = await page
        .locator("header")
        .first()
        .evaluate((el) => el.getBoundingClientRect().bottom);
      expect(top).toBeGreaterThanOrEqual(header - 1);
    });
  }

  for (const scheme of ["light", "dark"] as const) {
    test(`paints the ${scheme} theme's background, edge to edge`, async ({
      page,
    }) => {
      await page.emulateMedia({ colorScheme: scheme });
      await page.goto("/");
      const [body, wrapper, hero] = await page.evaluate(() => {
        const bg = (el: Element | null) =>
          el ? getComputedStyle(el).backgroundColor : "missing";
        return [
          bg(document.body),
          bg(document.querySelector("main")?.parentElement ?? null),
          getComputedStyle(document.querySelector("main section")!)
            .backgroundImage,
        ];
      });
      expect(wrapper).toBe(body);
      expect(hero).toBe("none");
    });
  }
});

test.describe("phone", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("has no sideways scroll", async ({ page }) => {
    await page.goto("/");
    const [scroll, client] = await page.evaluate(() => [
      document.documentElement.scrollWidth,
      document.documentElement.clientWidth,
    ]);
    expect(scroll).toBeLessThanOrEqual(client);
  });

  test("the menu opens, links to a section, and closes", async ({ page }) => {
    await page.goto("/");
    await expect(
      page.getByRole("navigation", { name: "Main" }).getByRole("link", {
        name: "Product",
        exact: true,
      }),
    ).toBeHidden();
    await page.getByRole("button", { name: "Open menu" }).click();
    const menu = page.locator("#landing-mobile-menu");
    await menu.getByRole("link", { name: "Safety" }).click();
    await expect(page).toHaveURL(/\/#safety$/);
    await expect(menu).toBeHidden();
    await expect(page.locator("section#safety")).toBeInViewport();
  });
});
