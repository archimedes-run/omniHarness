import { expect, test, type Page } from "@playwright/test";

import { THREAD, stub } from "./chat-bar-stubs";
import { lowContrastText } from "./contrast-probe";

/**
 * The "Building: <name>" chip above the chat bar (Spec 010 FR-003), in both
 * themes: shown while the chat has a build open, measured against WCAG AA
 * with the probe contrast.spec.ts uses, and its × sends the drop (a DELETE,
 * which writes nothing to the config store) and takes the chip away.
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

async function stubBuilder(page: Page, savedVersion: number | null) {
  const seen = { deletes: 0 };
  let building: object | null = {
    kind: "agent",
    name: "inbox-triage",
    title: "Inbox triage",
    draft_id: "d-1",
    saved_version: savedVersion,
  };
  await page.route("**/api/threads/*/builder", async (route) => {
    if (route.request().method() === "DELETE") {
      seen.deletes += 1;
      building = null;
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          thread_id: THREAD,
          dropped: true,
          refused_cards: 1,
        }),
      });
    }
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ thread_id: THREAD, building }),
    });
  });
  return seen;
}

for (const scheme of ["light", "dark"] as const) {
  test(`${scheme}: the Building chip meets WCAG AA`, async ({ page }) => {
    await inTheme(page, scheme);
    await stub(page);
    await stubBuilder(page, 2);
    await page.goto(`/workspace/chats/${THREAD}`, { waitUntil: "networkidle" });
    expect(
      await page.evaluate(() =>
        document.documentElement.classList.contains("dark"),
      ),
    ).toBe(scheme === "dark");
    const chip = page.getByTestId("building-chip");
    await expect(chip).toBeVisible();
    await expect(chip).toContainText("Building: Inbox triage");
    await expect(page.getByTestId("building-saved")).toContainText(
      "saved as version 2",
    );
    const found = await page.evaluate(lowContrastText);
    expect(
      found,
      found
        .map((f) => `${f.ratio}/${f.need} "${f.text}" ${f.color} [${f.cls}]`)
        .join("\n"),
    ).toEqual([]);
  });
}

test("× drops the draft and the chip goes away", async ({ page }) => {
  await stub(page);
  const seen = await stubBuilder(page, null);
  await page.goto(`/workspace/chats/${THREAD}`, { waitUntil: "networkidle" });
  await expect(page.getByTestId("building-chip")).toBeVisible();
  await page
    .getByRole("button", {
      name: "Stop building Inbox triage and drop the draft",
    })
    .click();
  await expect(page.getByTestId("building-chip")).toHaveCount(0);
  expect(seen.deletes).toBe(1);
});

test("no chip when the chat is not building", async ({ page }) => {
  await stub(page);
  await page.route("**/api/threads/*/builder", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ thread_id: THREAD, building: null }),
    }),
  );
  await page.goto(`/workspace/chats/${THREAD}`, { waitUntil: "networkidle" });
  await expect(page.getByTestId("composer")).toBeVisible();
  await expect(page.getByTestId("building-chip")).toHaveCount(0);
});
