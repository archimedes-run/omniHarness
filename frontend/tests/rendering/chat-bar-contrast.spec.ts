import { expect, test, type Page } from "@playwright/test";

import { EIGHT_PLUS, THREAD, stub } from "./chat-bar-stubs";
import { lowContrastText } from "./contrast-probe";

/**
 * The chat bar and the top bar in both themes (Feature 006): every chip,
 * including the dashed warn chip of an unreachable integration, the "+"
 * picker open on Integrations, where the status words carry colour, and the
 * capsule's active state. Uses the same probe as contrast.spec.ts.
 */

async function inTheme(page: Page, scheme: "light" | "dark") {
  await page.emulateMedia({ colorScheme: scheme });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.addInitScript((t) => {
    try {
      localStorage.setItem("theme", t);
    } catch {}
  }, scheme);
}

async function noLowContrast(page: Page) {
  const found = await page.evaluate(lowContrastText);
  expect(
    found,
    found
      .map((f) => `${f.ratio}/${f.need} "${f.text}" ${f.color} [${f.cls}]`)
      .join("\n"),
  ).toEqual([]);
}

for (const scheme of ["light", "dark"] as const) {
  test(`${scheme}: the chat bar, its chips and its picker meet WCAG AA`, async ({
    page,
  }) => {
    await inTheme(page, scheme);
    await stub(page, EIGHT_PLUS);
    await page.goto(`/workspace/chats/${THREAD}`, { waitUntil: "networkidle" });
    expect(
      await page.evaluate(() =>
        document.documentElement.classList.contains("dark"),
      ),
    ).toBe(scheme === "dark");
    await expect(page.getByTestId("chip-project")).toBeVisible();
    await expect(page.getByText("Unreachable").first()).toBeVisible();
    await page
      .getByRole("button", { name: "Show 3 more integrations" })
      .click();
    await noLowContrast(page);
    await page.getByRole("button", { name: "Add context" }).click();
    await expect(page.getByTestId("integration-status").first()).toBeVisible();
    await page.waitForTimeout(400);
    await noLowContrast(page);
  });

  test(`${scheme}: the new chat and the top bar meet WCAG AA, and so does the capsule's active state`, async ({
    page,
  }) => {
    await inTheme(page, scheme);
    await stub(page, EIGHT_PLUS);
    await page.goto("/workspace/chats/new", { waitUntil: "networkidle" });
    await expect(page.getByTestId("starters")).toBeVisible();
    await noLowContrast(page);

    // The active button sits under the panel's scrim while the panel is
    // open, so its own text and background are measured directly.
    await page.locator('[data-capsule="agents"]').click();
    const active = page.locator('[data-capsule="agents"]');
    await expect(active).toHaveAttribute("aria-pressed", "true");
    const ratio = await active.evaluate((el) => {
      const canvas = document.createElement("canvas");
      canvas.width = canvas.height = 1;
      const ctx = canvas.getContext("2d", { willReadFrequently: true })!;
      const rgb = (css: string) => {
        ctx.clearRect(0, 0, 1, 1);
        ctx.fillStyle = css;
        ctx.fillRect(0, 0, 1, 1);
        return Array.from(ctx.getImageData(0, 0, 1, 1).data.slice(0, 3));
      };
      const lum = (c: number[]) =>
        c
          .map((v) => {
            const x = v / 255;
            return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4;
          })
          .reduce((a, v, i) => a + v * [0.2126, 0.7152, 0.0722][i]!, 0);
      const s = getComputedStyle(el);
      const [hi, lo] = [lum(rgb(s.color)), lum(rgb(s.backgroundColor))].sort(
        (a, b) => b - a,
      ) as [number, number];
      return (hi + 0.05) / (lo + 0.05);
    });
    expect(ratio).toBeGreaterThanOrEqual(4.5);
  });
}
