import { expect, test, type Page } from "@playwright/test";

import { lowContrastText } from "./contrast-probe";
import { ruleFile } from "./schedule-stubs";
import { stubStudio } from "./studio-stubs";

/**
 * Per-agent schedules (Feature 006-F), as the board draws them
 * (Agent-Studio.dc.html, Schedule and alerts): AA contrast in both themes on
 * the empty tab, the editor, the saved schedule, Overview's Next run and the
 * Automations list naming who each automation runs as; and the editor driven
 * from the keyboard alone.
 *
 * Set STUDIO_SHOTS to a directory to save each screen in both themes.
 */

test.use({ timezoneId: "America/New_York" });

async function inTheme(page: Page, scheme: "light" | "dark") {
  await page.emulateMedia({ colorScheme: scheme });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.addInitScript((t) => {
    try {
      localStorage.setItem("theme", t);
    } catch {}
  }, scheme);
}

async function noLowContrast(page: Page, where: string) {
  const found = await page.evaluate(lowContrastText);
  expect(
    found,
    `${where}\n` +
      found
        .map((f) => `${f.ratio}/${f.need} "${f.text}" ${f.color} [${f.cls}]`)
        .join("\n"),
  ).toEqual([]);
}

async function shot(page: Page, name: string) {
  const dir = process.env.STUDIO_SHOTS;
  if (dir) await page.screenshot({ path: `${dir}/${name}.png` });
}

for (const scheme of ["dark", "light"] as const) {
  test(`${scheme}: the Schedule tab, empty, editing and saved, meets AA`, async ({
    page,
  }) => {
    await inTheme(page, scheme);
    await stubStudio(page);
    await ruleFile(page);
    await page.goto("/workspace/chats?panel=agents&item=researcher", {
      waitUntil: "networkidle",
    });
    await page.getByTestId("studio-tab-schedule").click();
    const panel = page.getByRole("tabpanel", { name: "Schedule" });
    await expect(panel.getByTestId("schedule-none")).toContainText(
      "No schedule yet",
    );
    await page.waitForTimeout(150);
    await noLowContrast(page, "schedule empty");
    await shot(page, `schedule-empty-${scheme}`);

    await panel.getByTestId("schedule-add").click();
    const editor = panel.getByTestId("schedule-editor");
    await editor.getByTestId("schedule-preset-weekdays").check();
    await editor.getByTestId("schedule-time").fill("18:00");
    await page.waitForTimeout(150);
    await noLowContrast(page, "schedule editing");
    await shot(page, `schedule-editing-${scheme}`);

    await editor.getByTestId("schedule-preset-custom").check();
    await expect(editor.getByTestId("schedule-cron")).toHaveValue(
      "0 18 * * 1-5",
    );
    await noLowContrast(page, "schedule editing (custom cron)");
    await shot(page, `schedule-editing-custom-${scheme}`);
    await editor.getByTestId("schedule-preset-weekdays").check();
    await editor.getByTestId("schedule-save").click();

    await expect(panel.getByTestId("schedule-when")).toHaveText(
      "Weekdays at 6:00 PM · America/New_York",
    );
    await page.waitForTimeout(150);
    await noLowContrast(page, "schedule saved");
    await shot(page, `schedule-saved-${scheme}`);

    await page.getByTestId("studio-tab-overview").click();
    await expect(page.getByTestId("overview-next-run")).toContainText(
      "6:00 PM",
    );
    await page.waitForTimeout(150);
    await noLowContrast(page, "overview with next run");
    await shot(page, `overview-next-run-${scheme}`);

    await page.goto("/workspace/chats?panel=automations", {
      waitUntil: "networkidle",
    });
    await expect(page.getByTestId("rule-runs-as").first()).toHaveText(
      "Runs as Researcher",
    );
    await page.waitForTimeout(150);
    await noLowContrast(page, "automations listing");
    await shot(page, `automations-runs-as-${scheme}`);
  });
}

test("the schedule editor works from the keyboard alone", async ({ page }) => {
  await stubStudio(page);
  const rules = await ruleFile(page);
  await page.goto("/workspace/chats?panel=agents&item=researcher", {
    waitUntil: "networkidle",
  });
  await page.getByTestId("studio-tab-schedule").click();
  const add = page.getByTestId("schedule-add");
  await add.focus();
  await page.keyboard.press("Enter");
  const editor = page.getByTestId("schedule-editor");
  await expect(editor).toBeVisible();
  // The preset radios are one group: arrows move between them.
  await editor.getByTestId("schedule-preset-daily").focus();
  await page.keyboard.press("ArrowRight");
  await expect(editor.getByTestId("schedule-preset-weekdays")).toBeChecked();
  await page.keyboard.press("ArrowRight");
  await expect(editor.getByTestId("schedule-preset-weekly")).toBeChecked();
  await editor.getByTestId("schedule-day").focus();
  await page.keyboard.type("Tu"); // type-ahead: Tuesday
  await editor.getByTestId("schedule-save").focus();
  await page.keyboard.press("Enter");
  await expect.poll(() => rules.writes.length).toBe(1);
  expect(rules.writes[0]!.body).toMatchObject({ schedule: "0 9 * * 2" });
  await expect(page.getByTestId("schedule-edit")).toHaveAccessibleName(
    "Edit the schedule Tue at 9:00 AM · America/New_York",
  );
});
