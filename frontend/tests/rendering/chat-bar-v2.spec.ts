import { expect, test, type Page } from "@playwright/test";

import {
  EIGHT_PLUS,
  THREAD,
  bar,
  chip,
  message,
  openPicker,
  stub,
} from "./chat-bar-stubs";

/**
 * Chat-Bar-v2.dc.html: one chip per piece of context, removable on the bar
 * and in step with the "+" picker both ways; overflow; keyboard removal; the
 * "@" mention that keeps the typed text; the new-chat heading and starters.
 */

const NEW = "/workspace/chats/new";

async function pickFromMenu(page: Page, name: string) {
  await page.getByRole("option", { name: new RegExp(name) }).click();
}

test("@agent in a new chat keeps the text on both sides, adds the agent as a chip, and keeps the caret", async ({
  page,
}) => {
  const seen = await stub(page);
  await page.goto(NEW);
  await message(page).click();
  await page.keyboard.type("check @res");
  await pickFromMenu(page, "researcher");
  await page.keyboard.type("the calendar");
  await expect(message(page)).toHaveValue("check @researcher the calendar");
  await expect(chip(page, "agent", "researcher")).toBeVisible();
  await expect(chip(page, "agent", "Lead agent")).toHaveCount(0);
  await expect(page).toHaveURL(/\/workspace\/chats\/new$/);

  // Text after the caret survives too: "@" typed in the middle.
  await message(page).fill("check the calendar");
  await message(page).evaluate((el: HTMLTextAreaElement) =>
    el.setSelectionRange(6, 6),
  );
  await page.keyboard.type("@rel");
  await pickFromMenu(page, "release-manager");
  await expect(message(page)).toHaveValue(
    "check @release-manager the calendar",
  );
  expect(
    await message(page).evaluate(
      (el: HTMLTextAreaElement) => el.selectionStart,
    ),
  ).toBe("check @release-manager ".length);
  await expect(chip(page, "agent", "release-manager")).toBeVisible();

  // The chosen agent goes with the first run.
  await message(page).press("Enter");
  await expect.poll(() => seen.sent.length).toBe(1);
  expect(JSON.parse(seen.sent[0]!).context.agent_name).toBe("release-manager");
});

test("removing the chosen agent's chip goes back to the lead agent", async ({
  page,
}) => {
  await stub(page);
  await page.goto(NEW);
  await message(page).click();
  await page.keyboard.type("@res");
  await pickFromMenu(page, "researcher");
  await page.getByRole("button", { name: "Remove researcher" }).click();
  await expect(chip(page, "agent", "Lead agent")).toBeVisible();
  await expect(chip(page, "agent", "researcher")).toHaveCount(0);
});

test("a skill removed on the bar is off in the picker, and turning it on there brings the chip back", async ({
  page,
}) => {
  const seen = await stub(page);
  await page.goto(`/workspace/chats/${THREAD}`);
  await page.getByRole("button", { name: "Remove skill cite" }).click();
  await expect.poll(() => seen.skillPuts.length).toBe(1);
  expect(seen.skillPuts[0]).toEqual(["cite"]);
  await expect(chip(page, "skill", "cite")).toHaveCount(0);

  const picker = await openPicker(page);
  await picker.getByRole("tab", { name: "Skills" }).click();
  const cite = picker.getByRole("switch", {
    name: "Use skill cite in this chat",
  });
  await expect(cite).not.toBeChecked();
  await cite.click();
  await expect.poll(() => seen.skillPuts.length).toBe(2);
  expect(seen.skillPuts[1]).toEqual([]);
  await expect(chip(page, "skill", "cite")).toBeVisible();
});

test("an integration removed on the bar is off in the picker, and on again from there", async ({
  page,
}) => {
  const seen = await stub(page);
  await page.goto(`/workspace/chats/${THREAD}`);
  await page
    .getByRole("button", { name: "Remove Google Calendar from this chat" })
    .click();
  await expect.poll(() => seen.puts.length).toBe(1);
  await expect(chip(page, "integration", "Google Calendar")).toHaveCount(0);
  const picker = await openPicker(page);
  const sw = picker.getByRole("switch", {
    name: "Use Google Calendar in this chat",
  });
  await expect(sw).not.toBeChecked();
  await sw.click();
  await expect.poll(() => seen.puts.length).toBe(2);
  expect(seen.puts[1]).toContain("connector:GOOGLECALENDAR");
  await expect(chip(page, "integration", "Google Calendar")).toBeVisible();
});

test("overflow: two skills then +N, four integrations then +N; expanding is inline and keeps the bar's width; an unreachable one is never hidden", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await stub(page, EIGHT_PLUS);
  await page.goto(`/workspace/chats/${THREAD}`);
  const skills = bar(page).getByTestId("chip-skill");
  const ints = bar(page).getByTestId("chip-integration");
  await expect(skills).toHaveCount(2);
  await expect(ints).toHaveCount(4);
  await expect(chip(page, "integration", "dead-server")).toBeVisible();
  const width = (await bar(page).boundingBox())!.width;

  const moreSkills = page.getByRole("button", { name: "Show 4 more skills" });
  await expect(moreSkills).toHaveText("+4 skills");
  await moreSkills.click();
  await expect(skills).toHaveCount(6);
  await expect(
    page.getByRole("button", { name: "Show fewer skills" }),
  ).toHaveAttribute("aria-expanded", "true");

  await page.getByRole("button", { name: "Show 3 more integrations" }).click();
  await expect(ints).toHaveCount(7);
  expect((await bar(page).boundingBox())!.width).toBe(width);

  await page.getByRole("button", { name: "Show fewer skills" }).click();
  await expect(skills).toHaveCount(2);
});

test("an unhealthy integration stays a chip with a dashed warn border and says Unreachable", async ({
  page,
}) => {
  await stub(page, EIGHT_PLUS);
  await page.goto(`/workspace/chats/${THREAD}`);
  const dead = chip(page, "integration", "dead-server");
  await expect(dead).toContainText("Unreachable");
  await expect(dead).toHaveCSS("border-top-style", "dashed");
  await expect(chip(page, "integration", "alpha")).toHaveCSS(
    "border-top-style",
    "solid",
  );
  // Still removable from this chat (it stays connected).
  await expect(
    page.getByRole("button", { name: "Remove dead-server from this chat" }),
  ).toBeVisible();
});

test("keyboard: Backspace in an empty message focuses the last chip, a second removes it; arrows move; past the last is the message", async ({
  page,
}) => {
  const seen = await stub(page);
  await page.goto(`/workspace/chats/${THREAD}`);
  await expect(chip(page, "skill", "cite")).toBeVisible();
  await message(page).click();
  await page.keyboard.press("Backspace");
  await expect(chip(page, "skill", "cite")).toBeFocused();
  await page.keyboard.press("Backspace");
  await expect.poll(() => seen.skillPuts.length).toBe(1);
  expect(seen.skillPuts[0]).toEqual(["cite"]);
  await expect(chip(page, "skill", "changelog")).toBeFocused();

  await page.keyboard.press("ArrowLeft");
  await expect(chip(page, "integration", "Google Calendar")).toBeFocused();
  await page.keyboard.press("ArrowRight");
  await expect(chip(page, "skill", "changelog")).toBeFocused();
  await page.keyboard.press("ArrowRight");
  await expect(message(page)).toBeFocused();

  // Delete on a chip that cannot be removed does nothing.
  await message(page).press("Backspace");
  await page.keyboard.press("Home");
  await expect(bar(page).getByTestId("chip-project")).toBeFocused();
  await page.keyboard.press("ArrowRight");
  await expect(chip(page, "agent", "Lead agent")).toBeFocused();
  await page.keyboard.press("Delete");
  await expect(chip(page, "agent", "Lead agent")).toBeFocused();
});

test("sizes: chips are at least 32 px tall, the bar at least 900 px wide at 1440, the message 16 px from two rows up to ten", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await stub(page, EIGHT_PLUS);
  for (const url of [NEW, `/workspace/chats/${THREAD}`]) {
    await page.goto(url);
    await expect(bar(page).getByTestId("chip-skill").first()).toBeVisible();
    const box = await bar(page).boundingBox();
    expect(box!.width).toBeGreaterThanOrEqual(900);
    for (const el of await bar(page).locator("[data-chip-index]").all()) {
      expect((await el.boundingBox())!.height).toBeGreaterThanOrEqual(32);
    }
  }
  await expect(message(page)).toHaveCSS("font-size", "16px");
  const empty = (await message(page).boundingBox())!.height;
  expect(empty).toBeGreaterThanOrEqual(48);
  expect(empty).toBeLessThan(72);
  await message(page).fill(Array.from({ length: 20 }, (_, i) => i).join("\n"));
  const full = (await message(page).boundingBox())!.height;
  expect(full).toBeGreaterThan(200);
  expect(full).toBeLessThanOrEqual(250);
});

test("the new chat: a heading with the display name, and starters that fill the message without sending", async ({
  page,
}) => {
  const seen = await stub(page);
  await page.goto(NEW);
  await expect(
    page.getByRole("heading", { name: "What are we working on, Rishabh?" }),
  ).toBeVisible();
  const starters = page.getByTestId("starters").getByRole("button");
  await expect(starters).toHaveText([
    "Plan my week",
    "What's blocked?",
    "Review a coding session",
    "New automation",
  ]);
  await expect(page.getByText("Surprise")).toHaveCount(0);
  await starters.filter({ hasText: "What's blocked?" }).click();
  await expect(message(page)).toHaveValue(/^What's blocked right now\?/);
  await expect(message(page)).toBeFocused();
  await page.waitForTimeout(300);
  expect(seen.sent).toHaveLength(0);
});

test("with no name to tell, the heading does not guess one", async ({
  page,
}) => {
  await stub(page, { displayName: null });
  await page.goto(NEW);
  await expect(
    page.getByRole("heading", { name: "What are we working on?" }),
  ).toBeVisible();
});

test("when this chat's skills cannot be read, the skill chips cannot be removed and the picker says why", async ({
  page,
}) => {
  await stub(page, { skillsFail: true });
  await page.goto(`/workspace/chats/${THREAD}`);
  await expect(chip(page, "skill", "cite")).toContainText(
    "This chat's skills could not be read",
  );
  await expect(
    page.getByRole("button", { name: "Remove skill cite" }),
  ).toHaveCount(0);
  const picker = await openPicker(page);
  await picker.getByRole("tab", { name: "Skills" }).click();
  await expect(picker).toContainText("could not be read");
  await expect(picker.getByRole("switch")).toHaveCount(0);
});

test("the model control shows its provider's logo when it can be told", async ({
  page,
}) => {
  await stub(page, {
    models: [{ name: "gpt-5", supports_thinking: false }],
  });
  await page.goto(NEW);
  const model = page.getByRole("button", { name: /^Model: gpt-5/ });
  await expect(model.getByRole("img", { name: "OpenAI logo" })).toBeVisible();
});
