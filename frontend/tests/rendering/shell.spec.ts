import { expect, test, type Page } from "@playwright/test";

/**
 * The app shell (Feature 006 Phase 1): the capsule, its panels as sheets over
 * the current page, and the command palette.
 *
 * NO BACKEND: every API a panel or the palette reads is intercepted, so a
 * failure here is about the shell, not a missing gateway.
 */

const json = (body: unknown, status = 200) => ({
  status,
  contentType: "application/json",
  body: JSON.stringify(body),
});

const now = () => new Date().toISOString();

const PROJECT = {
  id: "p1",
  name: "Beta launch",
  why: "Ship the public beta",
  status: "active",
  context: null,
  version: 1,
  created_at: now(),
  updated_at: now(),
  open_tasks: 1,
  overdue: 0,
  done_tasks: 0,
};

const rule = (id: string) => ({
  id,
  type: "cron",
  enabled: true,
  match: { schedule: "45 8 * * 1-5", timezone: "UTC" },
  prompt: `Brief me about the launch (${id}).`,
  destination: "auto",
  urgent: false,
  activity: "evaluated-never-fired",
  last_evaluated_at: null,
  last_evaluated: "not-recorded",
  last_fired_at: null,
  last_outcome: null,
});

async function serve(page: Page, { rules = 2, failing = {} } = {}) {
  const fail = (key: string) => failing[key];
  await page.route("**/api/agents", (route) =>
    fail("agents")
      ? route.fulfill(json({ detail: "boom" }, fail("agents")))
      : route.fulfill(
          json({
            agents: [
              {
                name: "launch-researcher",
                description: "Finds launch facts",
                model: null,
                tool_groups: null,
                skills: null,
              },
            ],
          }),
        ),
  );
  await page.route("**/api/skills", (route) =>
    route.fulfill(
      json({
        skills: [
          {
            name: "launch-checklist",
            description: "A checklist for a launch",
            category: "public",
            license: "MIT",
            enabled: true,
          },
        ],
      }),
    ),
  );
  await page.route("**/api/triggers/rules", (route) =>
    route.fulfill(
      json({
        engine_enabled: true,
        rules_error: null,
        version: "v1",
        writable: false,
        not_writable_reason: null,
        rules: Array.from({ length: rules }, (_, i) =>
          rule(i === 0 ? "launch-brief" : `rule-${i}`),
        ),
      }),
    ),
  );
  await page.route("**/api/triggers/firings", (route) =>
    route.fulfill(json({ firings: [] })),
  );
  await page.route("**/api/automations/templates", (route) =>
    route.fulfill(json([])),
  );
  await page.route("**/api/ledger/projects", (route) =>
    fail("projects")
      ? route.fulfill(json({ detail: "ledger unreadable" }, fail("projects")))
      : route.fulfill(json([PROJECT])),
  );
  await page.route("**/api/ledger/projects/p1", (route) =>
    route.fulfill(
      json({
        project: PROJECT,
        goals: [],
        tasks: [
          {
            id: "t1",
            project_id: "p1",
            short_id: "T-1",
            title: "Write the launch post",
            status: "todo",
            owner: null,
            due_date: null,
            goal_id: null,
            version: 1,
            done_at: null,
          },
        ],
        notes: [],
        links: [],
      }),
    ),
  );
  await page.route("**/threads/search", (route) =>
    route.fulfill(
      json([
        {
          thread_id: "th1",
          updated_at: now(),
          values: { title: "Launch day plan" },
          metadata: {},
        },
      ]),
    ),
  );
  await page.route("**/api/tool-sources*", (route) =>
    route.fulfill(
      json({
        thread_id: null,
        failing: 0,
        connectors_available: false,
        sources: [],
      }),
    ),
  );
  await page.route("**/api/confirmations", (route) =>
    route.fulfill(json({ actions: [], readable: true, error: "" })),
  );
  await page.route("**/api/inbox/alerts", (route) =>
    route.fulfill(json({ alerts: [], waiting_count: 0 })),
  );
}

const capsule = (page: Page, id: string) =>
  page.locator(`[data-capsule="${id}"]`);
const sheet = (page: Page) => page.getByTestId("panel-sheet");

test("the capsule is on every workspace page", async ({ page }) => {
  await serve(page);
  for (const path of [
    "/workspace/chats",
    "/workspace/chats/new",
    "/workspace/connections",
    "/workspace/settings/safety",
    "/workspace/home",
  ]) {
    await page.goto(path);
    const bar = page.getByRole("toolbar", { name: "Tools" });
    await expect(bar, path).toBeVisible();
    // Only the four panels: Search has its own button in the right cell.
    await expect(bar.getByRole("button")).toHaveText([
      "Agents",
      "Skills",
      "Automations",
      "Tasks",
    ]);
  }
});

test("a panel opens over the page with its name in the URL, and Esc brings you back with focus on the trigger", async ({
  page,
}) => {
  await serve(page);
  await page.goto("/workspace/connections?tab=suite");
  await capsule(page, "agents").click();

  await expect(sheet(page)).toBeVisible();
  await expect(page.getByRole("dialog", { name: "Agents" })).toBeVisible();
  // Path and its other params kept; the panel added.
  const opened = new URL(page.url());
  expect(opened.pathname).toBe("/workspace/connections");
  expect(opened.searchParams.get("tab")).toBe("suite");
  expect(opened.searchParams.get("panel")).toBe("agents");

  await page.keyboard.press("Escape");
  await expect(sheet(page)).toHaveCount(0);
  const closed = new URL(page.url());
  expect(closed.pathname).toBe("/workspace/connections");
  expect(closed.search).toBe("?tab=suite");
  await expect(capsule(page, "agents")).toBeFocused();
});

test("closing a panel you arrived on by link keeps the page's own params", async ({
  page,
}) => {
  await serve(page);
  // No entry was pushed for this panel, so closing rewrites the URL itself.
  await page.goto("/workspace/connections?tab=suite&panel=agents");
  await expect(sheet(page)).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(sheet(page)).toHaveCount(0);
  const url = new URL(page.url());
  expect(url.pathname).toBe("/workspace/connections");
  expect(url.search).toBe("?tab=suite");
  // Focus lands on the panel's capsule button, not on nothing.
  await expect(capsule(page, "agents")).toBeFocused();
});

test("the close button closes it too, and focus returns", async ({ page }) => {
  await serve(page);
  await page.goto("/workspace/chats");
  await capsule(page, "skills").click();
  await expect(sheet(page)).toBeVisible();
  await page.getByTestId("panel-close").click();
  await expect(sheet(page)).toHaveCount(0);
  expect(new URL(page.url()).searchParams.has("panel")).toBe(false);
  await expect(capsule(page, "skills")).toBeFocused();
});

test("focus stays inside the open panel", async ({ page }) => {
  await serve(page);
  await page.goto("/workspace/chats");
  await capsule(page, "tasks").click();
  await expect(page.getByText("Beta launch").first()).toBeVisible();
  for (let i = 0; i < 15; i += 1) {
    await page.keyboard.press("Tab");
    const inside = await page.evaluate(() =>
      Boolean(document.activeElement?.closest('[data-testid="panel-sheet"]')),
    );
    expect(inside, `Tab ${i + 1} left the panel`).toBe(true);
  }
});

test("closing returns you to the same scroll position", async ({ page }) => {
  await serve(page, { rules: 40 });
  await page.goto("/workspace/automations");
  await expect(page.getByText("rule-39")).toBeVisible();
  const scroller = page.getByTestId("workspace-scroll");
  await scroller.evaluate((el) => (el.scrollTop = 600));
  const before = await scroller.evaluate((el) => el.scrollTop);
  expect(before).toBeGreaterThan(500);

  await capsule(page, "agents").click();
  await expect(sheet(page)).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(sheet(page)).toHaveCount(0);
  expect(await scroller.evaluate((el) => el.scrollTop)).toBe(before);
});

test("Back closes an open panel", async ({ page }) => {
  await serve(page);
  await page.goto("/workspace/chats");
  await capsule(page, "automations").click();
  await expect(sheet(page)).toBeVisible();
  await page.goBack();
  await expect(sheet(page)).toHaveCount(0);
  expect(new URL(page.url()).pathname).toBe("/workspace/chats");
});

test("a link to a panel opens it", async ({ page }) => {
  await serve(page);
  await page.goto("/workspace/chats?panel=tasks");
  await expect(page.getByRole("dialog", { name: "Tasks" })).toBeVisible();
  await expect(sheet(page).getByText("Beta launch").first()).toBeVisible();
});

for (const [id, text] of [
  ["agents", "launch-researcher"],
  ["skills", "launch-checklist"],
  ["automations", "launch-brief"],
  ["tasks", "Beta launch"],
] as const) {
  test(`the ${id} panel loads its content`, async ({ page }) => {
    await serve(page);
    await page.goto("/workspace/chats");
    await capsule(page, id).click();
    await expect(sheet(page)).toHaveAttribute("data-panel", id);
    await expect(sheet(page).getByText(text).first()).toBeVisible();
    await expect(page.getByTestId("panel-failed")).toHaveCount(0);
  });
}

test("a link inside a panel navigates and closes the panel", async ({
  page,
}) => {
  await serve(page);
  await page.goto("/workspace/chats");
  await capsule(page, "tasks").click();
  await sheet(page)
    .getByRole("link", { name: /Beta launch/ })
    .click();
  await expect(page).toHaveURL(/\/workspace\/projects\/p1$/);
  await expect(sheet(page)).toHaveCount(0);
});

test("at phone width the capsule fits, and every control is a 44 px target", async ({
  page,
}) => {
  await page.setViewportSize({ width: 375, height: 740 });
  await serve(page);
  await page.goto("/workspace/chats");
  const bar = page.getByRole("toolbar", { name: "Tools" });
  await expect(bar).toBeVisible();
  const box = (await bar.boundingBox())!;
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(375);
  for (const button of await bar.getByRole("button").all()) {
    const b = (await button.boundingBox())!;
    expect(
      b.height,
      (await button.getAttribute("aria-label")) ?? "",
    ).toBeGreaterThanOrEqual(44);
    expect(
      b.width,
      (await button.getAttribute("aria-label")) ?? "",
    ).toBeGreaterThanOrEqual(44);
  }
  // The page does not scroll sideways.
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
  // The sidebar opens from the capsule bar.
  const trigger = page.getByRole("button", { name: "Open sidebar" });
  const t = (await trigger.boundingBox())!;
  expect(t.height).toBeGreaterThanOrEqual(44);
  await trigger.click();
  const newChat = page
    .locator('[data-sidebar="menu-button"]')
    .filter({ hasText: "New chat" });
  expect((await newChat.boundingBox())!.height).toBeGreaterThanOrEqual(44);
  // The sheet takes the whole screen at this width.
  await page.keyboard.press("Escape");
  await capsule(page, "agents").click();
  const s = (await sheet(page).boundingBox())!;
  expect(s.width).toBeGreaterThanOrEqual(374);
});

// ── Command palette ─────────────────────────────────────────────────────

const palette = (page: Page) => page.getByTestId("command-palette");

test("⌘K and Ctrl+K open the palette from anywhere, even a text field", async ({
  page,
}) => {
  await serve(page);
  await page.goto("/workspace/chats");
  await page.keyboard.press("Meta+k");
  await expect(palette(page)).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(palette(page)).toHaveCount(0);

  await page.keyboard.press("Control+k");
  await expect(palette(page)).toBeVisible();
  await page.keyboard.press("Escape");

  // From inside a text field.
  await page.getByRole("searchbox").first().focus();
  await page.keyboard.press("Control+k");
  await expect(palette(page)).toBeVisible();
});

test('"/" opens the palette, except while typing in a text field', async ({
  page,
}) => {
  await serve(page);
  await page.goto("/workspace/chats");
  await page.locator("body").click({ position: { x: 600, y: 500 } });
  await page.keyboard.press("/");
  await expect(palette(page)).toBeVisible();
  // The "/" that opened it is not typed into the search.
  await expect(page.getByRole("combobox")).toHaveValue("");
  await page.keyboard.press("Escape");
  await expect(palette(page)).toHaveCount(0);

  const field = page.getByRole("searchbox").first();
  await field.focus();
  await page.keyboard.press("/");
  await expect(palette(page)).toHaveCount(0);
  await expect(field).toHaveValue("/");
});

test("the Search button opens the palette and focus returns to it", async ({
  page,
}) => {
  await serve(page);
  await page.goto("/workspace/chats");
  const search = page.getByTestId("search-button");
  await expect(search).toHaveText(/Search\s*(⌘K|Ctrl\+K)/);
  expect((await search.boundingBox())!.height).toBe(36);
  await search.click();
  await expect(palette(page)).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(search).toBeFocused();
});

test("searching finds chats, projects, tasks, agents, skills and automations", async ({
  page,
}) => {
  await serve(page);
  await page.goto("/workspace/chats");
  await page.keyboard.press("Control+k");
  await page.getByRole("combobox").fill("launch");
  const hit = (source: string) =>
    page.locator(`[data-testid="palette-hit"][data-source="${source}"]`);
  await expect(hit("chats")).toHaveText(["Launch day plan"]);
  await expect(hit("projects")).toContainText(["Beta launch"]);
  await expect(hit("tasks")).toContainText(["Write the launch post"]);
  await expect(hit("agents")).toContainText(["launch-researcher"]);
  await expect(hit("skills")).toContainText(["launch-checklist"]);
  await expect(hit("automations")).toContainText(["launch-brief"]);

  // Keyboard: the first result is selected; Enter goes there.
  await page.getByRole("combobox").fill("launch day");
  await expect(hit("chats")).toHaveText(["Launch day plan"]);
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/workspace\/chats\/th1$/);
  await expect(palette(page)).toHaveCount(0);
});

test("a source that cannot be searched says so, rather than showing nothing", async ({
  page,
}) => {
  await serve(page, { failing: { projects: 500 } });
  await page.goto("/workspace/chats");
  await page.keyboard.press("Control+k");
  await page.getByRole("combobox").fill("launch");
  await expect(
    page.locator(
      '[data-testid="palette-unsearchable"][data-source="projects"]',
    ),
  ).toContainText("Cannot search Projects");
  // The others still answer.
  await expect(
    page.locator('[data-testid="palette-hit"][data-source="chats"]'),
  ).toHaveText(["Launch day plan"]);
});

test("theme commands change the theme (and tolerate no server preference)", async ({
  page,
}) => {
  await serve(page);
  const puts: unknown[] = [];
  await page.route("**/api/preferences/appearance", (route) => {
    if (route.request().method() === "PUT") {
      puts.push(route.request().postDataJSON());
    }
    return route.fulfill(json({ detail: "Not Found" }, 404));
  });
  await page.goto("/workspace/chats");
  const run = async (name: string) => {
    // As a person would: the previous command's palette has finished
    // closing before the next one opens. Opening a dialog while another is
    // still animating out can leave the new one not clickable.
    await expect(palette(page)).toHaveCount(0);
    await expect(page.locator('[data-slot="dialog-overlay"]')).toHaveCount(0);
    await page.keyboard.press("Control+k");
    await page.getByRole("combobox").fill(name);
    await page.getByRole("option", { name }).click();
    await expect(palette(page)).toHaveCount(0);
  };
  await run("Turn on dark theme");
  await expect(page.locator("html")).toHaveClass(/\bdark\b/);
  await run("Turn on light theme");
  await expect(page.locator("html")).toHaveClass(/\blight\b/);
  await expect(page.locator("html")).not.toHaveClass(/\bdark\b/);
  await run("Use system theme");
  expect(puts).toEqual([
    { appearance: "dark" },
    { appearance: "light" },
    { appearance: "system" },
  ]);
});

test("palette commands navigate and open panels", async ({ page }) => {
  await serve(page);
  await page.goto("/workspace/chats");
  const run = async (name: string) => {
    // As a person would: the previous command's palette has finished
    // closing before the next one opens. Opening a dialog while another is
    // still animating out can leave the new one not clickable.
    await expect(palette(page)).toHaveCount(0);
    await expect(page.locator('[data-slot="dialog-overlay"]')).toHaveCount(0);
    await page.keyboard.press("Control+k");
    await page.getByRole("combobox").fill(name);
    await page.getByRole("option", { name }).click();
  };
  await run("New agent");
  await expect(page).toHaveURL(/\/workspace\/agents\/new$/);
  await run("Connect Slack");
  await expect(page).toHaveURL(/\/workspace\/connections$/);
  await run("Open Settings");
  await expect(page).toHaveURL(/\/workspace\/settings/);
  await run("New chat");
  await expect(page).toHaveURL(/\/workspace\/chats\/new$/);

  // Opening a panel from the palette: URL synced, focus returns to where it
  // was before the palette (the body here, so the Tasks button stands in).
  await capsule(page, "agents").focus();
  await run("Open Tasks");
  await expect(page.getByRole("dialog", { name: "Tasks" })).toBeVisible();
  expect(new URL(page.url()).searchParams.get("panel")).toBe("tasks");
  await expect(palette(page)).toHaveCount(0);
  await page.keyboard.press("Escape");
  await expect(sheet(page)).toHaveCount(0);
  await expect(capsule(page, "agents")).toBeFocused();
});

test("palette options are reachable by keyboard and named", async ({
  page,
}) => {
  await serve(page);
  await page.goto("/workspace/chats");
  await page.keyboard.press("Control+k");
  await expect(
    page.getByRole("combobox", { name: "Search and commands" }),
  ).toBeFocused();
  const options = page.getByRole("option");
  await expect(options.first()).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("ArrowDown");
  await expect(options.nth(1)).toHaveAttribute("aria-selected", "true");
  for (const name of [
    "Open Agents",
    "Open Skills",
    "Open Automations",
    "Open Tasks",
    "New chat",
    "New agent",
    "Connect Slack",
    "Turn on dark theme",
    "Turn on light theme",
    "Use system theme",
    "Open Settings",
  ]) {
    await expect(page.getByRole("option", { name })).toHaveCount(1);
  }
});

// ── Top bar: the capsule on the true centre ─────────────────────────────

/** Horizontal centres of the capsule and of the main area. */
async function centres(page: Page) {
  const main = (await page.getByTestId("capsule-bar").boundingBox())!;
  const cap = (await page.getByTestId("capsule").boundingBox())!;
  return {
    main: main.x + main.width / 2,
    capsule: cap.x + cap.width / 2,
  };
}

for (const width of [1440, 1280, 1024]) {
  test(`at ${width} px the capsule sits on the main area's centre, within 1 px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 800 });
    await serve(page);
    for (const path of ["/workspace/chats/new", "/workspace/connections"]) {
      await page.goto(path);
      await expect(page.getByTestId("capsule")).toBeVisible();
      const c = await centres(page);
      expect(Math.abs(c.capsule - c.main), path).toBeLessThanOrEqual(1);
    }
  });
}

test("with the sidebar collapsed the capsule is still on the main area's centre", async ({
  page,
  context,
}) => {
  await context.addCookies([
    { name: "sidebar_state", value: "false", url: "http://localhost:3000" },
  ]);
  await page.setViewportSize({ width: 1280, height: 800 });
  await serve(page);
  await page.goto("/workspace/chats/new");
  await expect(page.getByTestId("capsule")).toBeVisible();
  const main = (await page.getByTestId("capsule-bar").boundingBox())!;
  expect(main.x).toBeLessThan(80);
  const c = await centres(page);
  expect(Math.abs(c.capsule - c.main)).toBeLessThanOrEqual(1);
});

test("a long title truncates on the left and never moves or overlaps the capsule", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await serve(page);
  await page.goto("/workspace/chats/new");
  await page.getByTestId("topbar-title").evaluate((el) => {
    el.textContent = "A very long thread title ".repeat(12);
  });
  const c = await centres(page);
  expect(Math.abs(c.capsule - c.main)).toBeLessThanOrEqual(1);
  const title = (await page.getByTestId("topbar-title").boundingBox())!;
  const cap = (await page.getByTestId("capsule").boundingBox())!;
  expect(title.x + title.width).toBeLessThanOrEqual(cap.x);
});

test("the capsule's sizes, and the active button: pressed, tinted, medium weight", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 800 });
  await serve(page);
  await page.goto("/workspace/chats");
  const cap = page.getByTestId("capsule");
  expect((await cap.boundingBox())!.height).toBe(44);
  await expect(cap).toHaveCSS("border-top-left-radius", "22px");
  const agents = capsule(page, "agents");
  expect((await agents.boundingBox())!.height).toBe(34);
  await expect(agents).toHaveAttribute("aria-pressed", "false");
  await agents.click();
  await expect(agents).toHaveAttribute("aria-pressed", "true");
  await expect(agents).toHaveCSS("font-weight", "500");
  const tint = await page.evaluate(() =>
    getComputedStyle(document.documentElement)
      .getPropertyValue("--primary-subtle")
      .trim(),
  );
  const bg = await agents.evaluate(
    (el) => getComputedStyle(el).backgroundColor,
  );
  const probe = await page.evaluate((c) => {
    const d = document.createElement("div");
    d.style.backgroundColor = c;
    document.body.appendChild(d);
    const out = getComputedStyle(d).backgroundColor;
    d.remove();
    return out;
  }, tint);
  expect(bg).toBe(probe);
  await expect(capsule(page, "skills")).toHaveAttribute(
    "aria-pressed",
    "false",
  );
});

test("below 900 px of main area the capsule shows icons only, named and with tooltips, centred, overlapping nothing", async ({
  page,
}) => {
  await page.setViewportSize({ width: 900, height: 800 });
  await serve(page);
  await page.goto("/workspace/chats/new");
  const cap = page.getByTestId("capsule");
  await expect(cap).toBeVisible();
  for (const [id, name] of [
    ["agents", "Agents"],
    ["skills", "Skills"],
    ["automations", "Automations"],
    ["tasks", "Tasks"],
  ] as const) {
    const b = capsule(page, id);
    await expect(b).toHaveAccessibleName(name);
    await expect(b.getByText(name)).toBeHidden();
  }
  await capsule(page, "skills").hover();
  await expect(page.getByRole("tooltip", { name: "Skills" })).toBeVisible();
  const c = await centres(page);
  expect(Math.abs(c.capsule - c.main)).toBeLessThanOrEqual(1);
  const box = (await cap.boundingBox())!;
  const title = (await page.getByTestId("topbar-title").boundingBox())!;
  const search = (await page.getByTestId("search-button").boundingBox())!;
  expect(title.x + title.width).toBeLessThanOrEqual(box.x);
  expect(box.x + box.width).toBeLessThanOrEqual(search.x);
});

test("with a panel open the top bar stays in view, so the capsule shows which panel it is", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 800 });
  await serve(page);
  await page.goto("/workspace/chats");
  await capsule(page, "agents").click();
  await expect(sheet(page)).toBeVisible();
  // A modal dialog turns pointer events off outside itself, and
  // elementFromPoint skips such elements: turn them back on for the button,
  // so only something drawn over it (the scrim) can hide it.
  const onTop = await capsule(page, "agents").evaluate((el: HTMLElement) => {
    const r = el.getBoundingClientRect();
    el.style.pointerEvents = "auto";
    const hit = document.elementFromPoint(
      r.left + r.width / 2,
      r.top + r.height / 2,
    );
    el.style.pointerEvents = "";
    return !!hit && el.contains(hit);
  });
  expect(onTop).toBe(true);
  await expect(capsule(page, "agents")).toHaveAttribute("aria-pressed", "true");
  const s = (await sheet(page).boundingBox())!;
  expect(s.y).toBeGreaterThanOrEqual(64);
});
