import { expect, test, type Page } from "@playwright/test";

import { lowContrastText } from "./contrast-probe";
import { stubStudio } from "./studio-stubs";

/**
 * The Agent & Skill Studio (006-G), against a real build of the app with the
 * gateway stubbed (studio-stubs.ts): every screen of the approved board in
 * both themes meets AA contrast, the editors work from the keyboard alone, and
 * phone width needs no sideways scroll.
 *
 * Set STUDIO_SHOTS to a directory to save every screen in both themes.
 */

test.use({ timezoneId: "America/New_York" });

const WRAP_UP_RULE = {
  id: "evening-wrap-up-schedule",
  agent: "evening-wrap-up",
  schedule: "30 18 * * 1-5",
  timezone: "America/New_York",
  destination: "auto",
  show_on_home: true,
  enabled: true,
  prompt:
    "Write today's wrap-up: what moved, what's stuck, and the top three tasks for tomorrow.",
  fired: true,
};
const FRIDAY_RULE = {
  ...WRAP_UP_RULE,
  id: "evening-wrap-up-schedule-2",
  schedule: "30 16 * * 5",
  show_on_home: false,
  prompt: "Week in review: wins, slips and one thing to drop next week.",
};

async function inTheme(page: Page, scheme: "light" | "dark") {
  await page.emulateMedia({ colorScheme: scheme });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.addInitScript((t) => {
    try {
      localStorage.setItem("theme", t);
    } catch {}
  }, scheme);
}

async function settle(page: Page) {
  await page.waitForTimeout(150);
}

async function check(page: Page, scheme: string, name: string) {
  await settle(page);
  const dir = process.env.STUDIO_SHOTS;
  if (dir) await page.screenshot({ path: `${dir}/${name}-${scheme}.png` });
  const found = await page.evaluate(lowContrastText);
  expect(
    found,
    `${name} (${scheme})\n` +
      found
        .map((f) => `${f.ratio}/${f.need} "${f.text}" ${f.color} [${f.cls}]`)
        .join("\n"),
  ).toEqual([]);
}

const sheet = (page: Page) => page.getByTestId("panel-sheet");

for (const scheme of ["light", "dark"] as const) {
  test(`${scheme}: the agents list and the agent stepper, every screen, meet AA`, async ({
    page,
  }) => {
    await inTheme(page, scheme);
    await stubStudio(page, { schedules: [WRAP_UP_RULE, FRIDAY_RULE] });
    await page.goto("/workspace/chats?panel=agents", {
      waitUntil: "networkidle",
    });
    await expect(page.getByTestId("agent-card-evening-wrap-up")).toContainText(
      "Active",
    );
    await expect(page.getByTestId("agent-card-researcher")).toContainText(
      "On demand",
    );
    await expect(page.getByTestId("agent-card-inbox-triage")).toContainText(
      "Draft",
    );
    await check(page, scheme, "02-agents-list");

    // A new agent: Step 1, the avatar picker, then drafted from one sentence.
    await page.getByTestId("agents-new").click();
    await expect(page.getByTestId("agent-step-setup")).toBeVisible();
    await check(page, scheme, "03-agent-new-step1");
    await page.getByTestId("avatar-change").click();
    await expect(
      page.getByRole("radiogroup", { name: "Choose an avatar" }),
    ).toBeVisible();
    await check(page, scheme, "04-agent-new-step1-avatar-picker");
    await page.getByTestId("avatar-change").click();
    await page
      .getByTestId("agent-sentence")
      .fill(
        "Every weekday morning, scan my inbox and calendar and send me a five-line plan for the day.",
      );
    await page.getByTestId("agent-draft").click();
    await expect(page.getByTestId("agent-drafted")).toBeVisible();
    await check(page, scheme, "05-agent-new-step1-drafted");
    await page.getByTestId("wizard-step-3").click();
    await check(page, scheme, "12b-agent-new-step3-drafted");
    await page.getByTestId("wizard-step-1").click();
    await page.getByTestId("agent-undo-draft").click();
    await expect(page.getByTestId("agent-instructions")).toHaveValue("");

    // An existing agent, every step.
    await page.getByTestId("wizard-back-list").click();
    await page.getByTestId("leave-discard").click();
    await page.getByTestId("agent-card-evening-wrap-up").click();
    await expect(page.getByTestId("agent-step-setup")).toBeVisible();
    await check(page, scheme, "05b-agent-edit-step1");
    await page.getByTestId("wizard-step-2").click();
    await page.getByTestId("integration-expand-connector:GMAIL").click();
    await check(page, scheme, "06-agent-edit-step2-integrations");
    await page.getByTestId("integration-all-connector:GMAIL").click();
    await check(page, scheme, "06b-agent-edit-step2-integrations-all");
    await page.getByTestId("config-tab-skills").click();
    await check(page, scheme, "07-agent-edit-step2-skills");
    await page.getByTestId("config-tab-autonomy").click();
    await check(page, scheme, "08-agent-edit-step2-autonomy");
    await page.getByTestId("wizard-step-3").click();
    await expect(page.getByTestId("schedule-card")).toHaveCount(2);
    // An edit marks the step and the header.
    await page.getByTestId("schedule-toggle").last().click();
    await expect(page.getByTestId("wizard-unsaved")).toBeVisible();
    await check(page, scheme, "10-agent-edit-step3-schedules");
    await page.getByTestId("schedule-add").first().click();
    await page
      .getByTestId("schedule-task")
      .fill(
        "Every Monday, list the three tasks most likely to slip this week and why.",
      );
    await check(page, scheme, "11-agent-edit-step3-add-schedule");
    await page.getByTestId("wizard-step-4").click();
    await check(page, scheme, "13-agent-edit-step4-review");

    // A new agent with no schedule yet.
    await page.getByTestId("wizard-back-list").click();
    await page.getByTestId("leave-discard").click();
    await page.getByTestId("agents-new").click();
    await page.getByTestId("agent-name").fill("Inbox zero coach");
    await page
      .getByTestId("agent-sentence")
      .fill(
        "Keeps my inbox near zero by labelling routine mail and drafting replies.",
      );
    await page.getByTestId("wizard-next").click();
    await page.getByTestId("wizard-next").click();
    await expect(page.getByTestId("schedule-empty")).toBeVisible();
    await check(page, scheme, "12-agent-new-step3-empty");
  });

  test(`${scheme}: the skills list and the skill stepper, every screen, meet AA`, async ({
    page,
  }) => {
    await inTheme(page, scheme);
    await stubStudio(page);
    await page.goto("/workspace/chats?panel=skills", {
      waitUntil: "networkidle",
    });
    await expect(
      page.getByTestId("skill-card-project-status-format"),
    ).toBeVisible();
    await check(page, scheme, "14-skills-list");
    await page.getByTestId("skill-card-project-status-format").click();
    await expect(page.getByTestId("skill-step-details")).toBeVisible();
    await check(page, scheme, "15-skill-edit-step1-details");
    await page.getByTestId("wizard-step-2").click();
    await check(page, scheme, "16-skill-edit-step2-instructions");
    await page.getByTestId("wizard-step-3").click();
    await check(page, scheme, "17-skill-edit-step3-files");
    await page.getByTestId("wizard-step-4").click();
    await expect(page.getByTestId("skill-test-row")).toHaveCount(2);
    await check(page, scheme, "18-skill-edit-step4-test");
  });
}

test("the agent stepper works from the keyboard alone", async ({ page }) => {
  const seen = await stubStudio(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/workspace/chats?panel=agents", {
    waitUntil: "networkidle",
  });
  await expect(page.getByTestId("agent-card-researcher")).toBeVisible();
  // "N" opens a new agent from the list.
  await page.getByTestId("agent-card-researcher").focus();
  await page.keyboard.press("n");
  const name = page.getByTestId("agent-name");
  await expect(page.getByTestId("agent-step-setup")).toBeVisible();
  // Tab from the avatar card into the form; a picked avatar via arrow keys.
  await page.getByTestId("avatar-change").focus();
  await page.keyboard.press("Enter");
  await page.locator('[role="radio"][aria-checked="true"]').first().focus();
  await page.keyboard.press("ArrowRight");
  const picked = await page
    .locator('[role="radio"][aria-checked="true"]')
    .getAttribute("data-avatar-id");
  expect(picked).toBeTruthy();
  await expect(page.locator(`[data-avatar-id="${picked}"]`)).toBeFocused();
  await name.focus();
  await page.keyboard.type("Keyboard agent");
  await page.getByTestId("agent-instructions").focus();
  await page.keyboard.type("Say what moved today.");
  await page.keyboard.press("ControlOrMeta+Enter");
  await expect(page.getByTestId("agent-step-config")).toBeVisible();
  // The configuration cards are a tablist: arrows move, and a tool's switch
  // takes Space.
  await page.getByTestId("config-tab-integrations").focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByTestId("config-tab-skills")).toBeFocused();
  await page.keyboard.press("ArrowLeft");
  await page.getByTestId("integration-expand-builtin:web").focus();
  await page.keyboard.press("Enter");
  await page.getByTestId("tool-switch-web_search").focus();
  await page.keyboard.press("Space");
  await expect(page.getByTestId("tool-switch-web_search")).toHaveAttribute(
    "aria-checked",
    "true",
  );
  await page.keyboard.press("ControlOrMeta+Enter");
  // Add a schedule with the keyboard.
  await page.getByTestId("schedule-add").first().focus();
  await page.keyboard.press("Enter");
  await page.getByTestId("schedule-task").focus();
  await page.keyboard.type("Wrap up the day.");
  await page.getByTestId("schedule-save").focus();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("schedule-card")).toHaveCount(1);
  // Esc closes an inner editor first, then asks before leaving unsaved work.
  await page.getByTestId("schedule-edit").focus();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("schedule-editor")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("schedule-editor")).toHaveCount(0);
  await expect(sheet(page)).toBeVisible();
  // ⌘S saves from any step.
  await page.keyboard.press("ControlOrMeta+s");
  await expect.poll(() => seen.agentWrites.length).toBe(1);
  expect(seen.agentWrites[0]!.body).toMatchObject({
    name: "keyboard-agent",
    display_name: "Keyboard agent",
    tools: { integrations: ["builtin:web"], tools: ["web_search"] },
  });
  await expect.poll(() => seen.rules.writes.length).toBe(1);
});

test("Esc in an editor with unsaved changes asks first, and Esc on the list closes", async ({
  page,
}) => {
  const seen = await stubStudio(page);
  await page.goto("/workspace/chats?panel=agents&item=evening-wrap-up", {
    waitUntil: "networkidle",
  });
  await page.getByTestId("agent-name").fill("Evening digest");
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("leave-bar")).toBeVisible();
  await expect(sheet(page)).toBeVisible();
  await page.getByRole("button", { name: "Keep editing" }).click();
  await expect(page.getByTestId("agent-name")).toHaveValue("Evening digest");
  await page.keyboard.press("Escape");
  await page.getByTestId("leave-discard").click();
  await expect(page.getByTestId("agents-list")).toBeVisible();
  expect(seen.agentWrites).toEqual([]);
  await page.keyboard.press("Escape");
  await expect(sheet(page)).toHaveCount(0);
});

test("at phone width nothing scrolls sideways and the controls are 44 px", async ({
  page,
}) => {
  await page.setViewportSize({ width: 375, height: 740 });
  await stubStudio(page, { schedules: [WRAP_UP_RULE] });
  await page.goto("/workspace/chats?panel=agents&item=evening-wrap-up", {
    waitUntil: "networkidle",
  });
  for (const step of [1, 2, 3, 4]) {
    await page.getByTestId(`wizard-step-${step}`).click();
    await settle(page);
    const overflow = await page
      .getByTestId("wizard-body")
      .evaluate((el) => el.scrollWidth - el.clientWidth);
    expect(overflow, `step ${step} scrolls sideways`).toBeLessThanOrEqual(1);
  }
  for (const id of [
    "wizard-save",
    "wizard-prev",
    "panel-close",
    "wizard-back-list",
  ]) {
    const box = await page.getByTestId(id).first().boundingBox();
    expect(box, id).not.toBeNull();
    expect(box!.height, id).toBeGreaterThanOrEqual(44);
  }
});
