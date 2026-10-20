import { expect, test, type Page } from "@playwright/test";

/**
 * Phase 2.5 — what a page ships, asserted against the production build.
 *
 * Measured before: every workspace page shipped ~2.3 MB of parsed JavaScript,
 * including katex, shiki and @langchain/core, because the settings dialog
 * (markdown) and the LangGraph SDK client (thread search) were imported by the
 * sidebar. Chat pages also shipped codemirror for an editor shown only when an
 * artifact is opened.
 *
 * Markers are strings those libraries' code contains. A non-chat page carrying
 * one has pulled the library back in.
 */
const HEAVY: Record<string, RegExp> = {
  codemirror: /@codemirror|cm-editor/,
  // Strings the libraries cannot minify away: katex's error text, shiki's
  // error class name. ("katex"/"shiki" alone also match loader paths and
  // CSS variable names, so they say nothing about the library being loaded.)
  katex: /KaTeX parse error/,
  shiki: /ShikiError/,
  "mermaid (library)": /mermaidAPI|mermaid-js\/mermaid/,
  "@langchain/core": /lc_serializable/,
  xterm: /xterm/,
};

// Every sidebar destination and settings section that is not a chat. Memory
// and About render markdown on purpose, so they are listed separately below.
const NON_CHAT = [
  "/workspace/chats",
  "/workspace/automations",
  "/workspace/agents",
  "/workspace/sessions",
  "/workspace/connections",
  "/workspace/settings/safety",
  "/workspace/settings/activity",
  "/workspace/settings/appearance",
  "/workspace/settings/memory",
  "/workspace/settings/account",
  "/workspace/settings/tools",
];

async function scriptsOf(page: Page, route: string): Promise<string[]> {
  const bodies: Promise<string>[] = [];
  page.on("response", (r) => {
    if (r.request().resourceType() === "script") {
      bodies.push(r.text().catch(() => ""));
    }
  });
  await page.goto(route, { waitUntil: "networkidle" });
  // Components that mount after the first paint load their chunks a moment
  // later; without this settle, a static import there went unseen.
  await page.waitForTimeout(1500);
  return Promise.all(bodies);
}

function heavyIn(scripts: string[]): string[] {
  return Object.entries(HEAVY)
    .filter(([, re]) => scripts.some((s) => re.test(s)))
    .map(([name]) => name);
}

for (const route of NON_CHAT) {
  test(`${route} ships none of the heavy chat libraries`, async ({ page }) => {
    const scripts = await scriptsOf(page, route);
    expect(
      scripts.length,
      "no scripts captured: the check saw nothing",
    ).toBeGreaterThan(5);
    expect(heavyIn(scripts)).toEqual([]);
  });
}

// Feature 006: Home is where a new chat starts (Main board), so its chat bar
// carries the chat runtime, loaded after the dashboard paints; it is held to
// the empty chat page's budget.
for (const route of ["/workspace/chats/new", "/workspace/home"])
  test(`${route}: an empty chat page ships no code editor, highlighter or math renderer`, async ({
    page,
  }) => {
    // Phase 2.6: shiki and katex load when a message needs them
    // (markdown-lazy.spec.ts proves they do load then), codemirror when an
    // artifact's editor opens.
    const scripts = await scriptsOf(page, route);
    expect(
      scripts.length,
      "no scripts captured: the check saw nothing",
    ).toBeGreaterThan(5);
    // Each named: expect.not.arrayContaining passes unless ALL are present,
    // which let a statically imported katex through.
    const heavy = heavyIn(scripts);
    for (const library of ["codemirror", "shiki", "katex"]) {
      expect(heavy, `${library} shipped with an empty chat page`).not.toContain(
        library,
      );
    }
  });

/**
 * Feature 006: the capsule's panels are dynamic imports. A page that is not
 * the panel's own ships none of its code until the user reaches for it.
 * Markers are literals only that panel's component contains.
 */
const PANEL_MARKERS: Record<string, RegExp> = {
  agents: /Custom agents are turned off/,
  skills: /mode=skill/,
  automations: /every weekday at 9, brief me/,
  tasks: /What you are working toward/,
};

for (const route of [
  "/workspace/chats",
  "/workspace/connections",
  "/workspace/settings/safety",
]) {
  test(`${route} ships no capsule panel until one is opened`, async ({
    page,
  }) => {
    const scripts = await scriptsOf(page, route);
    expect(scripts.length, "no scripts captured").toBeGreaterThan(5);
    const shipped = Object.entries(PANEL_MARKERS)
      .filter(([, re]) => scripts.some((s) => re.test(s)))
      .map(([name]) => name);
    expect(shipped).toEqual([]);
  });
}

test("POSITIVE CONTROL: opening a panel loads its code (the markers are real)", async ({
  page,
}) => {
  const bodies: Promise<string>[] = [];
  page.on("response", (r) => {
    if (r.request().resourceType() === "script") {
      bodies.push(r.text().catch(() => ""));
    }
  });
  await page.goto("/workspace/chats", { waitUntil: "networkidle" });
  for (const id of Object.keys(PANEL_MARKERS)) {
    await page.locator(`[data-capsule="${id}"]`).click();
    await expect(page.getByTestId("panel-sheet")).toHaveAttribute(
      "data-panel",
      id,
    );
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("panel-sheet")).toHaveCount(0);
  }
  await page.waitForTimeout(500);
  const scripts = await Promise.all(bodies);
  for (const [id, re] of Object.entries(PANEL_MARKERS)) {
    expect(
      scripts.some((s) => re.test(s)),
      `${id} panel code never loaded`,
    ).toBe(true);
  }
});
