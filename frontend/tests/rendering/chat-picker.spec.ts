import { expect, test, type Page } from "@playwright/test";

import { THREAD, openPicker, stub } from "./chat-bar-stubs";
import { lowContrastText } from "./contrast-probe";

/**
 * The "+" picker against Chat-Picker.dc.html, in both themes: the panel on
 * the surface colour with a 14 px radius, tabs that do not stretch, 28 px
 * logo tiles (radius 7) with a code tile for an unbranded local server, the
 * 36 x 20 switch, 13 px underlined row links, and the inline Connect's words
 * readable at WCAG AA.
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

const box = (page: Page, selector: string) =>
  page
    .locator(selector)
    .first()
    .evaluate((el) => {
      const r = el.getBoundingClientRect();
      const s = getComputedStyle(el);
      return {
        w: Math.round(r.width),
        h: Math.round(r.height),
        radius: s.borderTopLeftRadius,
        bg: s.backgroundColor,
        font: s.fontSize,
        underline: s.textDecorationLine,
      };
    });

for (const scheme of ["light", "dark"] as const) {
  test(`${scheme}: the Integrations tab matches the board's sizes`, async ({
    page,
  }) => {
    await inTheme(page, scheme);
    await stub(page);
    await page.goto(`/workspace/chats/${THREAD}`, { waitUntil: "networkidle" });
    const picker = await openPicker(page);
    await picker.getByRole("tab", { name: "Integrations" }).click();
    await expect(
      picker.getByTestId("integration-status").first(),
    ).toBeVisible();

    const panel = await box(page, '[data-testid="context-picker"]');
    expect(panel.radius).toBe("14px");
    // The panel is the surface colour (card), not the raised popover, so
    // the raised search box shows on it as on the board.
    const card = await page.evaluate(() => {
      const probe = document.createElement("div");
      probe.className = "bg-card";
      document.body.appendChild(probe);
      const c = getComputedStyle(probe).backgroundColor;
      probe.remove();
      return c;
    });
    expect(panel.bg).toBe(card);

    // Tabs keep their own width; the active one is filled, without a border.
    const tabs = picker.getByRole("tab");
    const widths = await tabs.evaluateAll((els) =>
      els.map((e) => Math.round(e.getBoundingClientRect().width)),
    );
    expect(Math.max(...widths)).toBeLessThan(140);
    const active = picker.getByRole("tab", { name: "Integrations" });
    expect(
      await active.evaluate((e) => getComputedStyle(e).borderTopWidth),
    ).toBe("0px");

    // Logo tiles: 28 px, radius 7; a local server without a brand is a code
    // tile that still has a name.
    const row = (name: string) =>
      picker.getByRole("listitem").filter({ hasText: name });
    const slack = row("Slack").getByRole("img", { name: "Slack logo" });
    expect(await slack.evaluate((e) => getComputedStyle(e).width)).toBe("28px");
    expect(
      await slack.evaluate((e) => getComputedStyle(e).borderTopLeftRadius),
    ).toBe("7px");
    await expect(
      row("dead-server").getByRole("img", {
        name: "dead-server, a local MCP server",
      }),
    ).toBeVisible();

    // The switch is 36 x 20.
    const sw = await row("Gmail")
      .getByRole("switch")
      .evaluate((e) => {
        const r = e.getBoundingClientRect();
        return [Math.round(r.width), Math.round(r.height)];
      });
    expect(sw).toEqual([36, 20]);

    // Row actions are 13 px underlined links.
    const check = await row("dead-server")
      .getByRole("link", { name: /Check/ })
      .evaluate((e) => [
        getComputedStyle(e).fontSize,
        getComputedStyle(e).textDecorationLine,
      ]);
    expect(check).toEqual(["13px", "underline"]);
  });

  test(`${scheme}: the picker and a Connect message meet WCAG AA`, async ({
    page,
  }) => {
    await inTheme(page, scheme);
    // A blocked pop-up: the longest, reddest message the row can show.
    await page.addInitScript(() => {
      window.open = () => null;
    });
    await stub(page);
    await page.goto(`/workspace/chats/${THREAD}`, { waitUntil: "networkidle" });
    const picker = await openPicker(page);
    await picker.getByRole("tab", { name: "Integrations" }).click();
    await picker.getByRole("button", { name: "Connect Slack" }).click();
    await expect(picker.getByTestId("connect-message")).toHaveText(
      /blocked the sign-in pop-up/,
    );
    await page.waitForTimeout(400);
    const found = await page.evaluate(lowContrastText);
    expect(
      found,
      found
        .map((f) => `${f.ratio}/${f.need} "${f.text}" ${f.color} [${f.cls}]`)
        .join("\n"),
    ).toEqual([]);
  });
}
