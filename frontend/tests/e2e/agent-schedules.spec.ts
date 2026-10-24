import { expect, test } from "@playwright/test";

import { ruleFile } from "../rendering/schedule-stubs";
import { stubStudio } from "../rendering/studio-stubs";

/**
 * Per-agent schedules (Feature 006-F), end to end through the panels.
 *
 * MOCKED API, no backend: the e2e suite starts only the frontend. The rule
 * file is a stateful stand-in in the real response shapes
 * (tests/rendering/schedule-stubs.ts), layered over the Studio stubs.
 */

test.use({ timezoneId: "America/New_York" });

test("a schedule set on an agent shows as its Next run and in Automations as who it runs as", async ({
  page,
}) => {
  await stubStudio(page);
  const rules = await ruleFile(page);
  await page.goto("/workspace/chats?panel=agents&item=researcher", {
    waitUntil: "networkidle",
  });
  await expect(page.getByTestId("overview-next-run")).toContainText(
    "Not set up",
  );

  await page.getByTestId("studio-tab-schedule").click();
  await expect(page.getByTestId("schedule-none")).toContainText(
    "No schedule yet",
  );
  await page.getByTestId("schedule-add").click();
  const editor = page.getByTestId("schedule-editor");
  await editor.getByTestId("schedule-preset-weekdays").check();
  await editor.getByTestId("schedule-time").fill("18:00");
  await expect(editor.getByTestId("schedule-zone")).toHaveValue(
    "America/New_York",
  );
  await editor.getByTestId("schedule-save").click();

  await expect.poll(() => rules.writes.length).toBe(1);
  expect(rules.writes[0]).toMatchObject({
    method: "POST",
    agent: "researcher",
    body: {
      schedule: "0 18 * * 1-5",
      timezone: "America/New_York",
      telegram: true,
      show_on_home: true,
      version: "v1",
    },
  });
  const row = page.getByTestId("schedule-row");
  await expect(row.getByTestId("schedule-when")).toHaveText(
    "Weekdays at 6:00 PM · America/New_York",
  );
  await expect(row.getByTestId("schedule-telegram")).toBeChecked();
  await expect(row.getByTestId("schedule-home")).toBeChecked();

  // A delivery toggle saves at once, naming the version it was based on.
  await row.getByTestId("schedule-home").uncheck();
  await expect.poll(() => rules.writes.length).toBe(2);
  expect(rules.writes[1]).toMatchObject({
    method: "PUT",
    body: { show_on_home: false, telegram: true, version: "v2" },
  });
  await expect(row.getByTestId("schedule-home")).not.toBeChecked();

  await page.getByTestId("studio-tab-overview").click();
  await expect(page.getByTestId("overview-next-run")).toContainText("6:00 PM");

  await page.goto("/workspace/chats?panel=automations", {
    waitUntil: "networkidle",
  });
  const listed = page.locator(
    '[data-testid="rule"][data-rule="researcher-schedule"]',
  );
  await expect(listed.getByTestId("rule-runs-as")).toHaveText(
    "Runs as Researcher",
  );
  await expect(page.getByTestId("rule-detail-runs-as")).toHaveText(
    "Runs as Researcher",
  );
});

test("a drafted schedule becomes a real one only when the person presses its button", async ({
  page,
}) => {
  await stubStudio(page);
  const rules = await ruleFile(page);
  await page.goto("/workspace/chats?panel=agents&item=new", {
    waitUntil: "networkidle",
  });
  await page
    .getByLabel("Describe the agent in one sentence")
    .fill("Every weekday morning, tell me what is waiting");
  await page
    .getByTestId("agent-draft-bar")
    .getByRole("button", { name: "Draft" })
    .click();
  await expect(page.getByTestId("draft-note")).toContainText(
    "Every tab is filled in for review",
  );
  await page.getByTestId("studio-save").click();
  await expect(page.getByTestId("studio-item-morning-brief")).toHaveAttribute(
    "aria-current",
    "page",
  );
  expect(rules.writes, "a draft created a schedule by itself").toEqual([]);

  await page.getByTestId("studio-tab-schedule").click();
  const suggested = page.getByTestId("schedule-suggested");
  await expect(suggested).toContainText(
    "Weekdays at 7:30 AM · America/New_York",
  );
  await suggested.getByTestId("schedule-adopt").click();

  await expect.poll(() => rules.writes.length).toBe(1);
  expect(rules.writes[0]).toMatchObject({
    method: "POST",
    agent: "morning-brief",
    body: { schedule: "30 7 * * 1-5", timezone: "America/New_York" },
  });
  await expect(page.getByTestId("schedule-suggested")).toHaveCount(0);
  await expect(page.getByTestId("schedule-when")).toHaveText(
    "Weekdays at 7:30 AM · America/New_York",
  );
});

test("deleting a schedule removes it, after a confirmation", async ({
  page,
}) => {
  await stubStudio(page);
  const rules = await ruleFile(page);
  rules.rules.push({
    id: "evening-wrap-up-schedule",
    agent: "evening-wrap-up",
    schedule: "0 18 * * 1-5",
    timezone: "America/New_York",
    destination: "auto",
    show_on_home: true,
    enabled: true,
  });
  await page.goto("/workspace/chats?panel=agents&item=evening-wrap-up", {
    waitUntil: "networkidle",
  });
  await page.getByTestId("studio-tab-schedule").click();
  await page.getByTestId("schedule-edit").click();
  const editor = page.getByTestId("schedule-editor");
  await expect(editor.getByTestId("schedule-preset-weekdays")).toBeChecked();
  await expect(editor.getByTestId("schedule-time")).toHaveValue("18:00");
  await editor.getByTestId("schedule-delete").click();
  expect(rules.writes, "deleted before the confirmation").toEqual([]);
  await editor.getByTestId("schedule-delete-confirm").click();

  await expect.poll(() => rules.writes.length).toBe(1);
  expect(rules.writes[0]).toMatchObject({ method: "DELETE" });
  expect(rules.rules).toEqual([]);
  await expect(page.getByTestId("schedule-none")).toContainText(
    "No schedule yet",
  );
  await page.getByTestId("studio-tab-overview").click();
  await expect(page.getByTestId("overview-next-run")).toContainText(
    "Not set up",
  );
});
