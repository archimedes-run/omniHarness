import { expect, test, type Page } from "@playwright/test";

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

/**
 * Resolve a CSS custom property to sRGB and measure contrast IN THE BROWSER.
 *
 * Chromium reports oklch() tokens back from getComputedStyle as `lab(...)`, so
 * a string comparison cannot tell you whether a colour is readable. Painting
 * the resolved value onto a 1x1 canvas and reading the pixel gives the actual
 * sRGB the user's screen receives — a measurement of the render, not of the
 * stylesheet. That distinction is the whole reason this file exists.
 */
const RESOLVE = `(token) => {
  const probe = document.createElement("div");
  probe.style.color = "var(" + token + ")";
  document.body.appendChild(probe);
  const value = getComputedStyle(probe).color;
  probe.remove();
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 1;
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = value;
  ctx.fillRect(0, 0, 1, 1);
  const [r, g, b] = ctx.getImageData(0, 0, 1, 1).data;
  return [r, g, b];
}`;

function luminance([r, g, b]: number[]) {
  const lin = [r, g, b].map((c) => {
    const v = (c ?? 0) / 255;
    return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * lin[0]! + 0.7152 * lin[1]! + 0.0722 * lin[2]!;
}

function contrast(fg: number[], bg: number[]) {
  const a = luminance(fg);
  const b = luminance(bg);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

async function token(page: Page, name: string) {
  return await page.evaluate<number[]>(RESOLVE + `("${name}")`);
}

async function computed(page: Page, prop: string) {
  return page.evaluate(
    (p) => getComputedStyle(document.body).getPropertyValue(p).trim(),
    prop,
  );
}

async function load(page: Page, theme: string) {
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

  /**
   * The palette must be CHARCOAL, not neutral black.
   *
   * The .dark block used to be a neutral greyscale ramp anchored on
   * oklch(0.145 0 0) — near-black with zero chroma. Reported as "the dark
   * colour is just black"; the ask was #36454f, a blue-grey charcoal.
   *
   * Asserting on chroma rather than on an exact value leaves room to tune the
   * shade without rewriting the test, while still failing if someone
   * "simplifies" the palette back to a neutral ramp.
   */
  test("the dark background is charcoal, not neutral black", async ({
    page,
  }) => {
    await load(page, "dark");
    const [r, g, b] = await token(page, "--background");

    expect(
      { r, g, b },
      `--background renders rgb(${r}, ${g}, ${b}). A neutral ramp has r=g=b; ` +
        `charcoal is blue-grey, so blue must lead red.`,
    ).not.toEqual({ r: g, g, b: g });
    expect(
      b!,
      `blue (${b}) does not lead red (${r}) — this is not a charcoal`,
    ).toBeGreaterThan(r!);

    const lum = luminance([r!, g!, b!]);
    expect(
      lum,
      `--background is near-black (luminance ${lum.toFixed(4)})`,
    ).toBeGreaterThan(0.02);
  });

  /**
   * Every foreground token must be readable on the surface it sits on.
   *
   * WCAG AA for normal text is 4.5:1. This is the check that would have caught
   * a label rendering black on a near-black sidebar — for the tokens. It does
   * NOT catch a component that hardcodes `text-black` and ignores the token
   * entirely; the sidebar only renders under /workspace, which redirects
   * without a backend, so that case is covered by tests/unit/sidebar-tokens.
   */
  const PAIRS: Array<[string, string]> = [
    ["--foreground", "--background"],
    ["--muted-foreground", "--background"],
    ["--card-foreground", "--card"],
    ["--popover-foreground", "--popover"],
    ["--sidebar-foreground", "--sidebar"],
    ["--secondary-foreground", "--secondary"],
    ["--accent-foreground", "--accent"],
    ["--primary-foreground", "--primary"],
  ];

  for (const [fg, bg] of PAIRS) {
    test(`${fg} on ${bg} meets WCAG AA in dark mode`, async ({ page }) => {
      await load(page, "dark");
      const ratio = contrast(await token(page, fg), await token(page, bg));
      expect(
        ratio,
        `${fg} on ${bg} is ${ratio.toFixed(2)}:1, below the 4.5:1 AA floor for ` +
          `normal text — this is what "invisible until you hover over it" looks ` +
          `like as a number.`,
      ).toBeGreaterThanOrEqual(4.5);
    });
  }
});
