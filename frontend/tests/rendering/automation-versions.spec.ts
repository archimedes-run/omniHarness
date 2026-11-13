import { expect, test, type Page, type Route } from "@playwright/test";

import { lowContrastText } from "./contrast-probe";
import { stubStudio } from "./studio-stubs";
import { stubAutomations } from "./tasks-automations-stubs";

/**
 * Spec 010 Slice 1: an automation's versions, on the Automations page and in
 * Studio's schedule step. Every change is listed (when, which surface, what
 * changed in one line); "Undo" on the latest and "Restore this version" on an
 * older one post to the one undo route (the store path the chat builder will
 * use), naming the version the list was read at; a stale one says so; an
 * undone create shows "Deleted" with its own Undo. AA in both themes.
 *
 * NO BACKEND: the routes are intercepted. The store's behaviour (new
 * versions, baselines, stale refusal) is pytest's
 * (tests/automations/test_automation_versions.py).
 *
 * AUTOMATION_SHOTS=<dir> also saves a screenshot of each state.
 */

test.use({ timezoneId: "America/New_York" });

const json = (route: Route, body: unknown, status = 200) =>
  route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });

const BRIEF = {
  rule_id: "morning-brief",
  current: 3,
  unrecorded: false,
  exists: true,
  can_undo_create: false,
  versions: [
    {
      version: 3,
      at: "2026-11-13T15:20:00Z",
      who: "user:u1",
      source: "manual",
      via: "studio",
      changed: ["match.schedule", "match.timezone"],
      deleted: false,
    },
    {
      version: 2,
      at: "2026-11-12T09:05:00Z",
      who: "user:u1",
      source: "manual",
      via: "page",
      changed: ["prompt"],
      deleted: false,
    },
    {
      version: 1,
      at: "2026-11-12T09:05:00Z",
      who: "unknown",
      source: "existing",
      via: "",
      changed: [],
      deleted: false,
    },
  ],
};

const GONE = {
  rule_id: "standup",
  current: 2,
  unrecorded: false,
  exists: false,
  can_undo_create: true,
  versions: [
    {
      version: 2,
      at: "2026-11-13T15:30:00Z",
      who: "user:u1",
      source: "undo",
      via: "page",
      changed: ["deleted"],
      deleted: true,
    },
    {
      version: 1,
      at: "2026-11-13T15:00:00Z",
      who: "user:u1",
      source: "manual",
      via: "page",
      changed: ["created"],
      deleted: false,
    },
  ],
};

async function stubVersions(
  page: Page,
  histories: Record<string, unknown>,
  { stale = false } = {},
) {
  const undos: { url: string; body: unknown }[] = [];
  let reads = 0;
  await page.route("**/api/automations/rules/*/versions", (route) => {
    reads += 1;
    const id = decodeURIComponent(route.request().url().split("/").at(-2)!);
    const body = histories[id];
    return body
      ? json(route, body)
      : json(route, { detail: `No rule with id '${id}'.` }, 404);
  });
  await page.route("**/api/automations/rules/*/undo", (route) => {
    const req = route.request();
    undos.push({ url: req.url(), body: req.postDataJSON() });
    if (stale) {
      return json(
        route,
        {
          detail:
            "automation 'morning-brief' changed since you opened it (you had version 3, it is now version 4). Reload to see the change, then try again.",
        },
        409,
      );
    }
    const id = decodeURIComponent(req.url().split("/").at(-2)!);
    return json(route, histories[id]);
  });
  return { undos, reads: () => reads };
}

async function inTheme(page: Page, scheme: "light" | "dark") {
  await page.emulateMedia({ colorScheme: scheme });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.addInitScript((t) => {
    try {
      localStorage.setItem("theme", t);
    } catch {}
  }, scheme);
}

async function check(page: Page, scheme: string, name: string) {
  await page.waitForTimeout(200);
  const dir = process.env.AUTOMATION_SHOTS;
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

async function openVersions(page: Page) {
  await page.goto("/workspace/automations/morning-brief");
  await page.getByRole("tab", { name: "Versions" }).click();
  await page.getByTestId("rule-versions").waitFor();
}

test("the Versions tab lists each change with its source and what changed", async ({
  page,
}) => {
  await stubAutomations(page);
  await stubVersions(page, { "morning-brief": BRIEF });
  await openVersions(page);

  const rows = page.getByTestId("rule-version");
  await expect(rows).toHaveCount(3);
  await expect(rows.nth(0)).toContainText("Edited in Studio");
  await expect(rows.nth(0)).toContainText("current");
  await expect(rows.nth(0)).toContainText("Changed schedule, time zone");
  await expect(rows.nth(1)).toContainText("Edited on the Automations page");
  await expect(rows.nth(1)).toContainText("Changed what it asks");
  await expect(rows.nth(2)).toContainText("As it was when history began");
  await expect(rows.nth(0).getByTestId("rule-version-undo")).toBeVisible();
  await expect(rows.nth(1).getByTestId("rule-version-restore")).toHaveText(
    "Restore this version",
  );
  await expect(rows.nth(2).getByTestId("rule-version-restore")).toBeVisible();
});

test("Undo on the latest change restores the one before it, naming the version read", async ({
  page,
}) => {
  await stubAutomations(page);
  const seen = await stubVersions(page, { "morning-brief": BRIEF });
  await openVersions(page);

  await page.getByTestId("rule-version-undo").click();

  await expect.poll(() => seen.undos.length).toBe(1);
  expect(seen.undos[0]!.url).toContain(
    "/api/automations/rules/morning-brief/undo",
  );
  expect(seen.undos[0]!.body).toEqual({
    to_version: 2,
    base_version: 3,
    via: "page",
  });
  await expect(page.getByTestId("rule-restored")).toHaveText(
    "Restored version 2 as a new version.",
  );
});

test("Restore this version on an older one posts that version", async ({
  page,
}) => {
  await stubAutomations(page);
  const seen = await stubVersions(page, { "morning-brief": BRIEF });
  await openVersions(page);

  await page.getByTestId("rule-version-restore").last().click();

  await expect.poll(() => seen.undos.length).toBe(1);
  expect(seen.undos[0]!.body).toMatchObject({ to_version: 1, base_version: 3 });
});

test("a stale restore says so plainly and reloads the list", async ({
  page,
}) => {
  await stubAutomations(page);
  const seen = await stubVersions(
    page,
    { "morning-brief": BRIEF },
    { stale: true },
  );
  await openVersions(page);
  const before = seen.reads();

  await page.getByTestId("rule-version-undo").click();

  await expect(page.getByTestId("rule-restore-error")).toContainText(
    "changed since its history was loaded",
  );
  await expect.poll(() => seen.reads()).toBeGreaterThan(before);
});

test("an undone create shows Deleted, and its Undo brings back the version before", async ({
  page,
}) => {
  await stubAutomations(page);
  const seen = await stubVersions(page, { standup: GONE });
  await page.goto("/workspace/automations/standup");

  await expect(page.getByTestId("rule-deleted")).toContainText("Deleted.");
  // One Undo for it: the banner's, not also the latest row's.
  await expect(page.getByTestId("rule-version-undo")).toHaveCount(0);
  await page.getByTestId("rule-deleted-undo").click();

  await expect.poll(() => seen.undos.length).toBe(1);
  expect(seen.undos[0]!.body).toEqual({
    to_version: 1,
    base_version: 2,
    via: "page",
  });
});

test("an automation that never existed still says so", async ({ page }) => {
  await stubAutomations(page);
  await stubVersions(page, {});
  await page.goto("/workspace/automations/nothing-here");
  await expect(page.getByTestId("no-such-rule")).toBeVisible();
});

const WRAP_UP_RULE = {
  id: "evening-wrap-up-schedule",
  agent: "evening-wrap-up",
  schedule: "30 18 * * 1-5",
  timezone: "America/New_York",
  destination: "auto",
  show_on_home: true,
  enabled: true,
  prompt: "Write today's wrap-up.",
  fired: true,
};

const WRAP_UP_HISTORY = {
  ...BRIEF,
  rule_id: WRAP_UP_RULE.id,
  current: 2,
  can_undo_create: true,
  versions: [
    { ...BRIEF.versions[0]!, version: 2 },
    {
      ...BRIEF.versions[1]!,
      version: 1,
      via: "studio",
      changed: ["created"],
    },
  ],
};

async function openStudioSchedules(page: Page) {
  await page.goto("/workspace/chats?panel=agents", {
    waitUntil: "networkidle",
  });
  await page.getByTestId("agent-card-evening-wrap-up").click();
  await page.getByTestId("wizard-step-3").click();
  await page.getByTestId("schedule-versions-toggle").click();
  await page.getByTestId("rule-versions").waitFor();
}

test("Studio's schedule step shows a schedule's versions and restores through the same route", async ({
  page,
}) => {
  await stubStudio(page, { schedules: [WRAP_UP_RULE] });
  const seen = await stubVersions(page, { [WRAP_UP_RULE.id]: WRAP_UP_HISTORY });
  await openStudioSchedules(page);

  await expect(page.getByTestId("rule-version")).toHaveCount(2);
  await page.getByTestId("rule-version-undo").click();

  await expect.poll(() => seen.undos.length).toBe(1);
  expect(seen.undos[0]!.url).toContain(
    `/api/automations/rules/${WRAP_UP_RULE.id}/undo`,
  );
  expect(seen.undos[0]!.body).toEqual({
    to_version: 1,
    base_version: 2,
    via: "studio",
  });
});

test("Studio will not restore over unsaved schedule edits", async ({
  page,
}) => {
  await stubStudio(page, { schedules: [WRAP_UP_RULE] });
  await stubVersions(page, { [WRAP_UP_RULE.id]: WRAP_UP_HISTORY });
  await openStudioSchedules(page);
  await page.getByTestId("schedule-toggle").click();

  await expect(page.getByTestId("rule-versions-locked")).toBeVisible();
  await expect(page.getByTestId("rule-version-undo")).toBeDisabled();
});

for (const scheme of ["light", "dark"] as const) {
  test(`${scheme}: every versions state meets AA`, async ({ page }) => {
    await inTheme(page, scheme);
    await stubAutomations(page);
    await stubVersions(page, {
      "morning-brief": BRIEF,
      standup: GONE,
      "blocked-session": {
        ...BRIEF,
        rule_id: "blocked-session",
        current: 3,
        unrecorded: true,
        versions: BRIEF.versions.slice(1),
      },
    });
    await openVersions(page);
    await check(page, scheme, "01-versions");
    await page.getByTestId("rule-version-undo").click();
    await page.getByTestId("rule-restored").waitFor();
    await check(page, scheme, "02-restored");
    await page.goto("/workspace/automations/blocked-session");
    await page.getByRole("tab", { name: "Versions" }).click();
    await page.getByTestId("rule-versions").waitFor();
    await check(page, scheme, "03-hand-edit-unrecorded");
    await page.goto("/workspace/automations/standup");
    await page.getByTestId("rule-deleted").waitFor();
    await check(page, scheme, "04-deleted-undo");
  });

  test(`${scheme}: Studio's schedule versions meet AA`, async ({ page }) => {
    await inTheme(page, scheme);
    await stubStudio(page, { schedules: [WRAP_UP_RULE] });
    await stubVersions(page, { [WRAP_UP_RULE.id]: WRAP_UP_HISTORY });
    await openStudioSchedules(page);
    await check(page, scheme, "05-studio-schedule-versions");
  });
}
