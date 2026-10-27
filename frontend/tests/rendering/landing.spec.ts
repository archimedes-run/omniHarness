import { expect, test } from "@playwright/test";

import { NAV_LINKS } from "../../src/components/landing/links";

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
      // The theme really applied: next-themes sets class="dark" on <html>.
      await expect(page.locator("html")).toHaveClass(
        scheme === "dark" ? /\bdark\b/ : /^(?!.*\bdark\b)/,
      );
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

/**
 * The header is also the blog's and the docs' navbar, so its anchors must
 * work from another page. /blog and /en/docs currently fail to render in a
 * production build on main too (a Nextra layout error, unrelated to the
 * header), so the header's own hrefs are followed from another route here,
 * and the /blog version is kept as a fixme until those pages render.
 */
for (const { href } of NAV_LINKS.filter((l) => l.href.startsWith("/#"))) {
  test(`${href} lands on its section from another page`, async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/login", { waitUntil: "networkidle" });
    // A plain link with the header's href, followed as a browser would.
    await page.evaluate((h) => {
      const a = document.createElement("a");
      a.href = h;
      document.body.append(a);
      a.click();
    }, href);
    await expect(page).toHaveURL(new RegExp(`${href.replace("/", "\\/")}$`));
    await expect(page.locator(`section${href.slice(1)}`)).toBeInViewport();
  });
}

test.fixme("a header anchor on the blog goes to the landing section", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/blog");
  await page
    .getByRole("navigation", { name: "Main" })
    .getByRole("link", { name: "Safety", exact: true })
    .click();
  await expect(page).toHaveURL(/\/#safety$/);
  await expect(page.locator("section#safety")).toBeInViewport();
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

  test("Escape closes the menu and returns focus to its button", async ({
    page,
  }) => {
    await page.goto("/");
    const button = page.getByRole("button", { name: "Open menu" });
    const box = await button.boundingBox();
    expect(box!.width).toBeGreaterThanOrEqual(44);
    expect(box!.height).toBeGreaterThanOrEqual(44);
    await button.click();
    const menu = page.locator("#landing-mobile-menu");
    await expect(menu).toBeVisible();
    await menu.getByRole("link", { name: "Product" }).focus();
    await page.keyboard.press("Escape");
    await expect(menu).toBeHidden();
    await expect(page.getByRole("button", { name: "Open menu" })).toBeFocused();
  });
});
