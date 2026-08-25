import { expect, test } from "@playwright/test";

/**
 * Does toggling the theme change WHAT THE USER SEES?
 *
 * This is the test PR #20 should have shipped. That PR added
 * tests/unit/theme.test.ts, which parses globals.css and asserts `.dark` and
 * `:root` declare different values for the governing tokens. It passes. It
 * passed the whole time dark mode was visibly broken, because a token that
 * differs in the stylesheet tells you nothing about whether any pixel moves —
 * a later declaration in the same rule can override it and the parse test is
 * none the wiser. Asserting on the source is not asserting on the render.
 *
 * We measured in #25 that CI can run rendering assertions. This is the first
 * one that defends a feature rather than proving the capability.
 *
 * WHY `document.body` AND WHY THE LANDING PAGE. The base layer sets
 * `body { @apply bg-background }`, so body is the element that carries the
 * theme background on every route. `/` is static — no backend, no auth — so a
 * failure here cannot be the API being down, which would be a finding about
 * something else wearing this test's name (Article XII).
 */

const BODY = "body";

async function computed(page: import("@playwright/test").Page, prop: string) {
  return page.evaluate(
    (p) => getComputedStyle(document.body).getPropertyValue(p).trim(),
    prop,
  );
}

async function load(page: import("@playwright/test").Page, theme: string) {
  // next-themes persists under the `theme` key and reads it before paint.
  // Seeding via addInitScript rather than toggling-then-reloading avoids a
  // race where the assertion runs against the pre-hydration paint.
  await page.addInitScript(
    (t) => window.localStorage.setItem("theme", t),
    theme,
  );
  await page.goto("/");
  await page.waitForSelector(BODY);
}

test.describe("the theme toggle changes what the user sees", () => {
  /**
   * POSITIVE CONTROL — run first, and it must pass before any negative result
   * below is worth reading.
   *
   * It proves the harness can observe a theme-driven change in computed style
   * at all. Without it, "the background did not change" is equally consistent
   * with a broken theme and a browser that never applied the stylesheet.
   *
   * Text colour is the control because `text-foreground` is known to work.
   */
  test("POSITIVE CONTROL: text colour changes between light and dark", async ({
    page,
  }) => {
    await load(page, "light");
    const lightText = await computed(page, "color");

    await load(page, "dark");
    const darkText = await computed(page, "color");

    expect(
      lightText,
      "body has no computed text colour — the stylesheet never applied",
    ).toBeTruthy();
    expect(
      darkText,
      `body text colour is ${darkText} in both themes. The harness cannot see ` +
        `theme changes at all, so nothing else in this file means anything.`,
    ).not.toBe(lightText);
  });

  test('<html> receives class="dark"', async ({ page }) => {
    await load(page, "dark");
    const cls = await page.evaluate(() => document.documentElement.className);
    expect(
      cls,
      `<html class="${cls}"> — next-themes is not applying the class strategy, ` +
        `so no .dark rule can ever match`,
    ).toContain("dark");
  });

  test("the --background token resolves to different values", async ({
    page,
  }) => {
    await load(page, "light");
    const light = await computed(page, "--background");
    await load(page, "dark");
    const dark = await computed(page, "--background");

    expect(
      dark,
      `--background resolves to ${dark} in both themes — the .dark block is ` +
        `not winning, or is not being matched`,
    ).not.toBe(light);
  });

  // THE SUBJECT. Everything above localises a failure here.
  test("the body background a user actually sees changes", async ({ page }) => {
    await load(page, "light");
    const light = await computed(page, "background-color");

    await load(page, "dark");
    const dark = await computed(page, "background-color");

    expect(
      dark,
      `body renders ${dark} in dark mode and ${light} in light mode — the same. ` +
        `Tokens can differ and the class can be applied while a later ` +
        `declaration in the same rule overrides the utility.`,
    ).not.toBe(light);
  });
});
