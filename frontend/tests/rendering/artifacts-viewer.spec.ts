import { mkdirSync } from "node:fs";
import { join } from "node:path";

import { expect, test, type Locator, type Page } from "@playwright/test";

import { installFakeBridge } from "./apps/fake-bridge";
import { installCodeStore, THREAD, type CodeRec } from "./artifacts/fake-code";
import { IDS, installFakeStore, SAVED_IDS } from "./artifacts/fake-store";
import { lowContrastText } from "./contrast-probe";

/**
 * The artifact viewer (one header row of icon buttons next to the title, a
 * thin chip row, the content, a versions drawer and a docked ask box) in
 * its three hosts: the chat's side panel, the phone overlay and the full
 * page. ARTIFACT_SHOTS=<dir> saves the screenshots compared with the
 * design board.
 */

test.use({
  timezoneId: "UTC",
  launchOptions: {
    executablePath: process.env.CHROMIUM_EXECUTABLE ?? undefined,
  },
});

const SHOTS = process.env.ARTIFACT_SHOTS;
async function shot(page: Page, name: string) {
  if (!SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  await page.waitForTimeout(800);
  await page.screenshot({ path: join(SHOTS, `${name}.png`) });
}

const json = (body: unknown, status = 200) => ({
  status,
  contentType: "application/json",
  body: JSON.stringify(body),
});

const BUDGET = `<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><style>
body{margin:0;font:14px/1.5 system-ui,sans-serif;background:var(--card);color:var(--foreground)}
main{padding:20px;display:flex;flex-direction:column;gap:16px}
.row{display:flex;flex-wrap:wrap;gap:12px}
.box{flex:1 1 120px;background:var(--card);border:1px solid var(--border);border-radius:12px;padding:12px 14px}
.k{font-size:12px;color:var(--muted-foreground)}.v{font-size:22px;font-weight:600}
.bars{display:flex;align-items:flex-end;gap:10px;height:150px;border-bottom:1px solid var(--border)}
.bars i{flex:1;background:var(--primary);border-radius:4px 4px 0 0}
li{display:flex;justify-content:space-between;padding:6px 0;border-top:1px solid var(--border)}
ul{list-style:none;margin:0;padding:0}
</style></head><body><main>
<div class="row"><div class="box"><div class="k">Spent in October</div><div class="v">$2,486</div></div>
<div class="box"><div class="k">Income</div><div class="v">$4,200</div></div>
<div class="box"><div class="k">Left</div><div class="v">$1,714</div></div></div>
<div class="box"><b>Spending by category</b><div class="bars"><i style="height:100%"></i><i style="height:22%"></i><i style="height:12%"></i><i style="height:9%"></i><i style="height:7%"></i><i style="height:5%"></i></div></div>
<div class="box"><b>Recent</b><ul><li><span>Groceries</span><span>-$84.20</span></li><li><span>Salary</span><span>+$4,200.00</span></li><li><span>Dining</span><span>-$38.00</span></li></ul></div>
</main></body></html>`;

const APP = "BudgetTrackerAAAAAAAAA";
const SRC1 = {
  entry: "App.tsx",
  files: {
    "App.tsx":
      'import { useState } from "react";\nexport default function App() {\n  const [entries] = useState([]);\n  return <main className="grid">{entries.length}</main>;\n}\n',
  },
};
const SRC2 = {
  entry: "App.tsx",
  files: {
    "App.tsx":
      'import { useState } from "react";\nexport default function App() {\n  const [entries] = useState([]);\n  return <main className="grid gap-4">{entries.length}</main>;\n}\n',
  },
};
function budget(over: Partial<CodeRec> = {}): CodeRec {
  return {
    id: APP,
    kind: "react",
    title: "Budget Tracker",
    html: BUDGET,
    source: SRC2,
    history: [
      { note: null, source: SRC1 },
      { note: "Fixed the phone layout", source: SRC2 },
    ],
    ...over,
  };
}

/** The board's chat: one request, the reply and its card. */
async function installChat(page: Page, rec: CodeRec) {
  const messages = [
    {
      type: "human",
      id: "h1",
      content:
        "Build me a budget tracker with categories and charts, dark mode, works on my phone.",
    },
    {
      type: "ai",
      id: "ai-1",
      content: "",
      tool_calls: [
        { id: "c1", name: "artifact_create", args: { kind: rec.kind } },
      ],
    },
    {
      type: "tool",
      id: "t-1",
      name: "artifact_create",
      tool_call_id: "c1",
      content: `Created ${rec.kind} artifact ${rec.id}.`,
      artifact: {
        type: "omni_artifact",
        artifact_id: rec.id,
        version: rec.history?.length ?? 1,
        kind: rec.kind,
      },
    },
    {
      type: "ai",
      id: "a-1",
      content:
        "Done. It's open on the right. It saves your entries in the app, works offline and fits phone screens.",
    },
  ];
  const state = {
    values: { title: "Budget tracker app", messages },
    next: [],
    tasks: [],
    metadata: {},
    created_at: new Date().toISOString(),
    checkpoint: { thread_id: THREAD, checkpoint_id: "c1", checkpoint_ns: "" },
    parent_checkpoint: null,
  };
  const sent: string[] = [];
  await page.route("**/api/langgraph/**", (route) => {
    const req = route.request();
    const u = req.url();
    if (req.method() === "POST" && u.includes("/runs")) {
      sent.push(req.postData() ?? "");
      return route.fulfill({ status: 200, body: "" });
    }
    if (u.includes("/history")) return route.fulfill(json([state]));
    if (u.includes("/runs") || u.includes("/search"))
      return route.fulfill(json([]));
    return route.fulfill(json(state));
  });
  await page.route("**/api/confirmations", (route) =>
    route.fulfill(json({ actions: [], readable: true, error: "" })),
  );
  await page.route("**/api/inbox/alerts", (route) =>
    route.fulfill(json({ alerts: [], waiting_count: 0 })),
  );
  await page.route("**/api/threads/*/artifacts/manifests", (route) =>
    route.fulfill(json({ manifests: [] })),
  );
  return { sent };
}

/** Writes the code fake does not answer (save, rename, pin). */
async function codeWrites(page: Page, rec: CodeRec) {
  const writes: { method: string; path: string; body: unknown }[] = [];
  await page.route(
    new RegExp(`/api/artifacts/${rec.id}(/(save|unsave))?$`),
    async (route) => {
      const req = route.request();
      if (req.method() === "GET") return route.fallback();
      const body = req.postData() ? req.postDataJSON() : null;
      writes.push({
        method: req.method(),
        path: new URL(req.url()).pathname,
        body,
      });
      if (req.url().endsWith("/save")) rec.saved = true;
      if (req.url().endsWith("/unsave")) rec.saved = false;
      if (req.method() === "PATCH" && body?.title) rec.title = body.title;
      return route.fulfill(
        json({ id: rec.id, saved: rec.saved ?? true, title: rec.title }),
      );
    },
  );
  return writes;
}

async function theme(page: Page, t: "light" | "dark") {
  await page.addInitScript((x) => {
    try {
      localStorage.setItem("theme", x);
    } catch {}
  }, t);
}

async function openInChat(page: Page, rec: CodeRec) {
  await page.goto(`/workspace/chats/${THREAD}`);
  const card = page.locator(
    `[data-testid=artifact-card][data-artifact="${rec.id}"]`,
  );
  const panel = page.locator(
    `[data-testid=artifact-panel][data-artifact="${rec.id}"]`,
  );
  await expect(async () => {
    await card.getByTestId("artifact-card-open").click();
    await expect(panel).toBeVisible({ timeout: 1000 });
  }).toPass({ timeout: 15_000 });
  await expect(panel.getByTestId("artifact-frame")).toBeVisible({
    timeout: 15_000,
  });
  return panel;
}

async function aa(page: Page) {
  const low = await page.evaluate(lowContrastText);
  expect(
    low,
    low.map((f) => `${f.ratio}/${f.need} "${f.text}" [${f.cls}]`).join("\n"),
  ).toEqual([]);
}

async function noSidewaysScroll(page: Page) {
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    ),
  ).toBeLessThanOrEqual(1);
}

/** The header's buttons, in tab order, by accessible name. */
async function headerNames(panel: Locator) {
  return panel
    .getByTestId("artifact-header")
    .locator("button:visible, a:visible")
    .evaluateAll((els) =>
      els
        .filter((e) => getComputedStyle(e).opacity !== "0")
        .map((e) => e.getAttribute("aria-label") ?? e.textContent?.trim()),
    );
}

/** The open tooltip with exactly these words (one may still be fading out). */
async function expectTip(page: Page, words: string) {
  await expect(
    page
      .getByRole("tooltip")
      .filter({ hasText: words })
      .filter({ visible: true }),
  ).toHaveText(words);
}

test.describe("the board: a react app in the chat's side panel", () => {
  for (const t of ["dark", "light"] as const) {
    test(`one header row, chips, content, ask box; AA (${t})`, async ({
      page,
    }) => {
      await page.setViewportSize({ width: 1440, height: 1100 });
      await theme(page, t);
      const rec = budget();
      await installCodeStore(page, [rec]);
      await codeWrites(page, rec);
      await installChat(page, rec);
      const panel = await openInChat(page, rec);
      // ONE header row, in the board's order, every button named.
      expect(await headerNames(panel)).toEqual([
        "Version 2 of 2. Show versions",
        "Saved. More options",
        "Ask to change",
        "Preview",
        "Code",
        "Download",
        "Versions",
        "Pin to sidebar",
        "Open the chat that made it",
        "More actions",
        "Full screen",
        "Close",
      ]);
      const header = panel.getByTestId("artifact-header");
      expect((await header.boundingBox())!.height).toBe(60);
      for (const b of await header.locator("button[aria-label]").all()) {
        if ((await b.getAttribute("data-testid")) === "artifact-version-label")
          continue;
        if ((await b.getAttribute("data-testid")) === "artifact-store-saved")
          continue;
        const box = (await b.boundingBox())!;
        const name = (await b.getAttribute("aria-label")) ?? "";
        expect(Math.round(box.width), name).toBe(34);
        expect(Math.round(box.height), name).toBe(34);
      }
      await expect(panel.getByTestId("artifact-tab-preview")).toHaveAttribute(
        "aria-pressed",
        "true",
      );
      await expect(panel.getByTestId("artifact-check")).toHaveText(/Checked/);
      await expect(panel.getByTestId("artifact-lineage")).toHaveText(
        "From your request",
      );
      await expect(panel.getByTestId("artifact-ask-input")).toBeVisible();
      await page.mouse.move(0, 0);
      await shot(page, `board-react-${t}-1440`);
      await aa(page);

      // A tooltip on hover.
      await panel.getByTestId("artifact-versions-toggle").hover();
      await expectTip(page, "Versions · compare, restore");
      await shot(page, `board-tooltip-${t}`);
      await page.mouse.move(0, 0);

      // More open.
      await panel.getByTestId("artifact-more").click();
      const menu = page.getByTestId("artifact-more-menu");
      await expect(menu.getByRole("menuitem")).toHaveText([
        "Edit source",
        "Rename",
        "Duplicate",
        "Archive",
        "Open full page",
        "Details · checks, source, technical notes",
      ]);
      await shot(page, `board-more-${t}`);
      await aa(page);
      await page.keyboard.press("Escape");
      await expect(panel.getByTestId("artifact-more")).toBeFocused();

      // Versions drawer.
      await panel.getByTestId("artifact-version-label").click();
      const drawer = panel.getByTestId("artifact-versions");
      await expect(drawer).toBeVisible();
      expect(Math.round((await drawer.boundingBox())!.width)).toBe(260);
      await expect(drawer.getByTestId("artifact-version-summary")).toHaveText([
        "Fixed the phone layout",
        "First version",
      ]);
      await page.mouse.move(0, 0);
      await shot(page, `board-versions-${t}`);
      await aa(page);
      await page.keyboard.press("Escape");
      await expect(drawer).toHaveCount(0);
      await expect(panel.getByTestId("artifact-version-label")).toBeFocused();

      // Code.
      await panel.getByTestId("artifact-tab-code").click();
      await expect(panel.getByTestId("artifact-tab-code")).toHaveAttribute(
        "aria-pressed",
        "true",
      );
      await expect(panel.getByTestId("artifact-react-files")).toBeVisible();
      await expect(panel.getByTestId("artifact-devices")).toHaveCount(0);
      await page.mouse.move(0, 0);
      await shot(page, `board-code-${t}`);
      await aa(page);
    });
  }
});

test.describe("icon buttons", () => {
  test("a tooltip on keyboard focus too, and a visible focus ring", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1440, height: 1100 });
    const rec = budget();
    await installCodeStore(page, [rec]);
    await installChat(page, rec);
    const panel = await openInChat(page, rec);
    await panel.getByTestId("artifact-store-saved").focus();
    await page.keyboard.press("Tab"); // Ask to change
    await page.keyboard.press("Tab"); // Preview
    await expect(panel.getByTestId("artifact-tab-preview")).toBeFocused();
    await expectTip(page, "Preview");
    const ring = await panel
      .getByTestId("artifact-tab-preview")
      .evaluate((e) => getComputedStyle(e).outlineStyle);
    expect(ring).toBe("solid");
    await page.keyboard.press("Tab");
    await page.keyboard.press("Tab");
    await expect(panel.getByTestId("artifact-download-menu")).toBeFocused();
    await expectTip(page, "Download · Page (.html), Source (.zip)");
  });

  test("full screen in the side panel puts the preview full screen", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1440, height: 1100 });
    const rec = budget();
    await installCodeStore(page, [rec]);
    await installChat(page, rec);
    const panel = await openInChat(page, rec);
    await panel.getByTestId("artifact-fullscreen").click();
    await expect
      .poll(() =>
        page.evaluate(
          () => document.fullscreenElement?.getAttribute("data-testid") ?? "",
        ),
      )
      .toBe("artifact-preview-box");
    await page.evaluate(() => document.exitFullscreen());
  });
});

test.describe("touch", () => {
  test.use({ hasTouch: true, isMobile: true });
  test("no tooltip on a tap; 44 px targets", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const rec = budget();
    await installCodeStore(page, [rec]);
    await page.goto(`/workspace/artifacts/${APP}`);
    const panel = page.getByTestId("artifact-panel");
    await expect(panel.getByTestId("artifact-frame")).toBeVisible();
    await panel.getByTestId("artifact-tab-code").tap();
    await expect(panel.getByTestId("artifact-tab-code")).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await page.waitForTimeout(400);
    await expect(page.getByTestId("viewer-tooltip")).toHaveCount(0);
    const box = (await panel.getByTestId("artifact-tab-code").boundingBox())!;
    expect(box.width).toBe(44);
    expect(box.height).toBe(44);
  });
});

test.describe("what is shown per kind", () => {
  test("markdown on the full page: no Preview/Code, no sizes, no ask; one download", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    await installFakeStore(page, { saving: "on" });
    await page.goto(`/workspace/artifacts/${IDS.md}`, {
      waitUntil: "networkidle",
    });
    const panel = page.getByTestId("artifact-panel");
    await expect(panel.getByTestId("artifact-markdown")).toBeVisible();
    for (const id of [
      "artifact-tab-preview",
      "artifact-tab-code",
      "artifact-devices",
      "artifact-ask-change",
      "artifact-ask-box",
      "artifact-fullscreen",
      "artifact-close",
      "artifact-check",
      "artifact-download-menu",
    ]) {
      await expect(panel.getByTestId(id), id).toHaveCount(0);
    }
    await expect(panel.getByTestId("artifact-download")).toHaveAttribute(
      "href",
      `/api/artifacts/${IDS.md}/versions/2/download`,
    );
    // Content-originated static kind: a NEUTRAL chip.
    const chip = panel.getByTestId("artifact-lineage");
    await expect(chip).toHaveText(
      "Made from what the assistant read (web_fetch)",
    );
    await expect(chip).toHaveAttribute("data-tone", "neutral");
    await shot(page, "page-markdown-light");
    await aa(page);
  });

  test("download menus list exactly the route's forms", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    await installFakeStore(page, { saving: "on" });
    const open = (id: string) =>
      page.goto(`/workspace/artifacts/${id}`, { waitUntil: "networkidle" });
    await open(SAVED_IDS.html);
    await page.getByTestId("artifact-download-menu").click();
    const forms = page.getByTestId("artifact-download-form");
    await expect(forms).toHaveText(["Page (.html)", "Source (.zip)"]);
    await expect(forms.nth(0)).toHaveAttribute(
      "href",
      `/api/artifacts/${SAVED_IDS.html}/versions/1/download`,
    );
    await expect(forms.nth(1)).toHaveAttribute(
      "href",
      `/api/artifacts/${SAVED_IDS.html}/versions/1/download?source=zip`,
    );
    await page.keyboard.press("Escape");
    await open(SAVED_IDS.webapp);
    await expect(page.getByTestId("artifact-download-menu")).toHaveCount(0);
    await expect(page.getByTestId("artifact-download")).toHaveAttribute(
      "href",
      `/api/artifacts/${SAVED_IDS.webapp}/versions/1/download`,
    );
    await open(IDS.svg);
    await expect(page.getByTestId("artifact-download")).toHaveAttribute(
      "href",
      `/api/artifacts/${IDS.svg}/versions/1/download`,
    );
  });

  test("a build that failed downloads only its source", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    await installCodeStore(page, [
      { ...budget({ history: undefined }), buildFailed: true },
    ]);
    await page.goto(`/workspace/artifacts/${APP}`);
    const panel = page.getByTestId("artifact-panel");
    await expect(panel.getByTestId("artifact-build-failed")).toBeVisible();
    await expect(panel.getByTestId("artifact-download")).toHaveAttribute(
      "href",
      /download\?source=zip$/,
    );
    await expect(panel.getByTestId("artifact-fullscreen")).toHaveCount(0);
    await expect(panel.getByTestId("artifact-devices")).toHaveCount(0);
  });

  test("from a deleted chat: no chat button, the words in a chip", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    await installFakeStore(page, { saving: "on" });
    await page.goto(`/workspace/artifacts/${SAVED_IDS.orphan}`, {
      waitUntil: "networkidle",
    });
    const panel = page.getByTestId("artifact-panel");
    await expect(panel.getByTestId("artifact-origin-deleted")).toHaveText(
      "From a chat you deleted",
    );
    await expect(panel.getByTestId("artifact-open-chat")).toHaveCount(0);
  });
});

test.describe("the source chip", () => {
  const cases: [string, Partial<CodeRec>, string, string][] = [
    ["owner's request", {}, "From your request", "neutral"],
    [
      "content, runs code",
      { lineage: "content", lineage_source: "web_fetch" },
      "From content the assistant read (web_fetch)",
      "warn",
    ],
    [
      "content, unknown source",
      { lineage: "content", lineage_source: "unknown" },
      "Origin not determined",
      "warn",
    ],
    [
      "content, empty source",
      { lineage: "content", lineage_source: null },
      "Origin not determined",
      "warn",
    ],
  ];
  for (const [name, over, words, tone] of cases) {
    test(`react: ${name}`, async ({ page }) => {
      await installCodeStore(page, [budget({ history: undefined, ...over })]);
      await page.goto(`/workspace/artifacts/${APP}`);
      const chip = page.getByTestId("artifact-lineage");
      await expect(chip).toHaveText(words);
      await expect(chip).toHaveAttribute("data-tone", tone);
      await expect(page.getByTestId("artifact-panel")).not.toContainText(
        "(unknown)",
      );
    });
  }
  test("markdown: the owner's version is neutral too", async ({ page }) => {
    await installFakeStore(page, { saving: "on" });
    await page.goto(`/workspace/artifacts/${IDS.md}?v=1`, {
      waitUntil: "networkidle",
    });
    const chip = page.getByTestId("artifact-lineage");
    await expect(chip).toHaveText("From your request");
    await expect(chip).toHaveAttribute("data-tone", "neutral");
  });
});

test.describe("the checks chip", () => {
  test("passed: a button with a popover; Escape closes it and returns focus", async ({
    page,
  }) => {
    await installCodeStore(page, [budget()]);
    await page.goto(`/workspace/artifacts/${APP}`);
    const chip = page.getByTestId("artifact-check");
    await expect(chip).toHaveText(/Checked/);
    await expect(chip).toHaveAttribute("data-tone", "ok");
    await expect(chip).toHaveAttribute("aria-expanded", "false");
    await chip.click();
    await expect(chip).toHaveAttribute("aria-expanded", "true");
    await expect(page.getByTestId("artifact-check-popover")).toBeFocused();
    await expect(page.getByTestId("artifact-check-sentence")).toHaveText(
      "Checked: no network attempts seen; fits 360 to 1280 px in light and dark",
    );
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("artifact-check-popover")).toHaveCount(0);
    await expect(chip).toBeFocused();
  });

  test("failed: warning words and the details, with what will not run", async ({
    page,
  }) => {
    await installCodeStore(page, [
      budget({
        history: undefined,
        check: "failed",
        findings: ["Will not run in the frame: fetch('https://x.example')"],
      }),
    ]);
    await page.goto(`/workspace/artifacts/${APP}`);
    const chip = page.getByTestId("artifact-check");
    await expect(chip).toHaveText(/Check failed/);
    await expect(chip).toHaveAttribute("data-tone", "warn");
    await chip.click();
    const details = page.getByTestId("artifact-check-details");
    await expect(details).toContainText("overflows sideways at 360 px");
    await expect(details).toContainText("Will not run in the frame");
  });
});

test.describe("versions", () => {
  test("Compare shows the code changes; Restore makes a new version", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1440, height: 1000 });
    const rec = budget();
    const log = await installCodeStore(page, [rec]);
    await page.goto(`/workspace/artifacts/${APP}`);
    const panel = page.getByTestId("artifact-panel");
    await expect(panel).toHaveAttribute("data-version", "2");
    await panel.getByTestId("artifact-versions-toggle").click();
    const v1 = panel.locator(
      "[data-testid=artifact-versions] li[data-version='1']",
    );
    await v1.getByTestId("artifact-version-compare").click();
    const dialog = page.getByTestId("artifact-compare");
    await expect(dialog).toContainText("Compare v1 with v2");
    await expect(dialog).toContainText("Code changes");
    await expect(dialog.locator("[data-row=del]")).toContainText(
      'className="grid"',
    );
    await expect(dialog.locator("[data-row=add]")).toContainText(
      'className="grid gap-4"',
    );
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    await v1.getByTestId("artifact-version-restore").click();
    await expect(panel).toHaveAttribute("data-version", "3");
    expect(log.writes.find((w) => w.path.endsWith("/restore"))?.body).toEqual({
      version: 1,
      base_version: 2,
    });
  });

  test("markdown: Compare is a line diff with unchanged lines collapsed", async ({
    page,
  }) => {
    await installFakeStore(page, { saving: "on" });
    await page.goto(`/workspace/artifacts/${IDS.md}`, {
      waitUntil: "networkidle",
    });
    await page.getByTestId("artifact-version-label").click();
    await page
      .locator("li[data-version='1']")
      .getByTestId("artifact-version-compare")
      .click();
    const dialog = page.getByTestId("artifact-compare");
    await expect(dialog).toContainText("Compare v1 with v2");
    await expect(dialog).not.toContainText("Code changes");
  });
});

test.describe("rename, save, pin", () => {
  test("inline rename: Enter saves, Escape cancels, leaving saves", async ({
    page,
  }) => {
    const { log } = await installFakeStore(page, { saving: "on" });
    await page.goto(`/workspace/artifacts/${IDS.md}`, {
      waitUntil: "networkidle",
    });
    const patches = () =>
      log.writes.filter((w) => w.method === "PATCH").map((w) => w.body);
    await page.getByTestId("artifact-title").click();
    const input = page.getByTestId("artifact-rename-input");
    await input.fill("Brief, renamed");
    await input.press("Enter");
    await expect.poll(patches).toEqual([{ title: "Brief, renamed" }]);
    await expect(page.getByTestId("artifact-title")).toHaveText(
      "Brief, renamed",
    );
    // Escape cancels.
    await page.getByTestId("artifact-title").click();
    await input.fill("Not this");
    await input.press("Escape");
    await expect(input).toHaveCount(0);
    await expect(page.getByTestId("artifact-title")).toHaveText(
      "Brief, renamed",
    );
    // The pencil (on focus) starts it too; leaving the field saves.
    await page.getByTestId("artifact-rename-pencil").focus();
    await page.keyboard.press("Enter");
    await input.fill("Blurred title");
    await page.getByTestId("artifact-markdown").click();
    await expect
      .poll(patches)
      .toEqual([{ title: "Brief, renamed" }, { title: "Blurred title" }]);
    // An empty title is not saved.
    await page.getByTestId("artifact-title").click();
    await input.fill("   ");
    await input.press("Enter");
    await expect.poll(() => patches().length).toBe(2);
  });

  test("Saved offers Unsave; Save in the same spot", async ({ page }) => {
    const { log } = await installFakeStore(page, { saving: "on" });
    await page.goto(`/workspace/artifacts/${IDS.md}`, {
      waitUntil: "networkidle",
    });
    await page.getByTestId("artifact-store-saved").click();
    await page.getByTestId("artifact-store-unsave").click();
    await expect(page.getByTestId("artifact-store-save")).toBeVisible();
    await page.getByTestId("artifact-store-save").click();
    await expect(page.getByTestId("artifact-store-saved")).toBeVisible();
    expect(log.writes.map((w) => w.path)).toEqual([
      `/api/artifacts/${IDS.md}/unsave`,
      `/api/artifacts/${IDS.md}/save`,
    ]);
  });

  test("a refused save rolls back", async ({ page }) => {
    await installFakeStore(page, { saving: "failing" });
    await page.goto(`/workspace/artifacts/${SAVED_IDS.react}`, {
      waitUntil: "networkidle",
    });
    await page.getByTestId("artifact-store-save").click();
    await expect(
      page.getByTestId("artifact-header").getByRole("alert"),
    ).toBeVisible();
    await expect(page.getByTestId("artifact-store-save")).toBeVisible();
  });

  test("Pin is a toggle", async ({ page }) => {
    const { log } = await installFakeStore(page, { saving: "on" });
    await page.goto(`/workspace/artifacts/${IDS.chart}`, {
      waitUntil: "networkidle",
    });
    const pin = page.getByTestId("artifact-pin");
    await expect(pin).toHaveAttribute("aria-pressed", "false");
    await pin.click();
    await expect(pin).toHaveAttribute("aria-pressed", "true");
    expect(log.writes.at(-1)?.body).toEqual({ pinned: true });
  });
});

test.describe("preview sizes", () => {
  test("Desktop, Tablet, Phone set the frame's width", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1000 });
    await installCodeStore(page, [budget()]);
    await page.goto(`/workspace/artifacts/${APP}`);
    const frame = page.getByTestId("artifact-device-frame");
    await expect(page.getByTestId("artifact-frame")).toBeVisible();
    const width = async () => Math.round((await frame.boundingBox())!.width);
    const full = await width();
    await page.getByTestId("artifact-device-tab").click();
    await expect(page.getByTestId("artifact-device-tab")).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(await width()).toBe(760);
    await page.getByTestId("artifact-device-phone").click();
    expect(await width()).toBe(380);
    await page.getByTestId("artifact-device-desk").click();
    expect(await width()).toBe(full);
  });
});

test.describe("asking for a change", () => {
  test("the docked box sends the reference and the words as the chat's next message", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1440, height: 1100 });
    const rec = budget();
    await installCodeStore(page, [rec]);
    const { sent } = await installChat(page, rec);
    const panel = await openInChat(page, rec);
    await panel.getByTestId("artifact-ask-change").click();
    const input = panel.getByTestId("artifact-ask-input");
    await expect(input).toBeFocused();
    await input.fill("add a monthly budget limit per category");
    await input.press("Enter");
    await expect
      .poll(() => sent.join("\n"))
      .toContain(
        `[artifact ${APP} v2] add a monthly budget limit per category`,
      );
    await expect(input).toHaveValue("");
  });

  test("a draft in the chat box is kept: the request goes in front of it", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1440, height: 1100 });
    const rec = budget();
    await installCodeStore(page, [rec]);
    const { sent } = await installChat(page, rec);
    const panel = await openInChat(page, rec);
    await page.locator("textarea[name='message']").fill("my draft");
    await panel.getByTestId("artifact-ask-input").fill("make it blue");
    await panel.getByTestId("artifact-ask-send").click();
    await expect(page.locator("textarea[name='message']")).toHaveValue(
      `[artifact ${APP} v2] make it blue\n\nmy draft`,
    );
    expect(sent).toEqual([]);
  });
});

test.describe("phone width", () => {
  for (const t of ["light", "dark"] as const) {
    test(`one header row, no sideways scroll at 390 and 360 (${t})`, async ({
      page,
    }) => {
      await page.setViewportSize({ width: 390, height: 844 });
      await theme(page, t);
      const rec = budget();
      await installCodeStore(page, [rec]);
      await installChat(page, rec);
      await page.goto(`/workspace/chats/${THREAD}`);
      const card = page.locator(`[data-testid=artifact-card]`);
      const overlay = page.getByTestId("artifact-panel-mobile");
      await expect(async () => {
        // The card's live frame can keep resizing it (never "stable"):
        // press regardless, and check that the overlay opened.
        const open = card.getByTestId("artifact-card-open");
        await open.scrollIntoViewIfNeeded();
        await open.click({ timeout: 3000, force: true });
        await expect(overlay).toBeVisible({ timeout: 2000 });
      }).toPass({ timeout: 40_000 });
      const panel = overlay.getByTestId("artifact-panel");
      await expect(panel.getByTestId("artifact-frame")).toBeVisible();
      await expect(panel).toHaveAttribute("data-compact", "true");
      // Kept in the row: Ask, Preview, Code, Download; the rest in More.
      for (const id of [
        "artifact-ask-change",
        "artifact-tab-preview",
        "artifact-tab-code",
        "artifact-download-menu",
        "artifact-more",
        "artifact-close",
      ]) {
        await expect(panel.getByTestId(id), id).toBeVisible();
      }
      const header = panel.getByTestId("artifact-header");
      await expect(header.getByTestId("artifact-versions-toggle")).toHaveCount(
        0,
      );
      await expect(header.getByTestId("artifact-fullscreen")).toHaveCount(0);
      const tops = await header
        .locator("button:visible, a:visible")
        .evaluateAll((els) =>
          els.map((e) => Math.round(e.getBoundingClientRect().top)),
        );
      expect(Math.max(...tops) - Math.min(...tops)).toBeLessThanOrEqual(8);
      await noSidewaysScroll(page);
      const right = await header.evaluate((h) =>
        Math.max(
          ...Array.from(h.querySelectorAll("button, a")).map(
            (e) => e.getBoundingClientRect().right,
          ),
        ),
      );
      expect(right).toBeLessThanOrEqual(390);
      await shot(page, `phone-390-${t}`);
      await aa(page);
      await panel.getByTestId("artifact-more").click();
      await expect(
        page.getByTestId("artifact-more-menu").getByRole("menuitem"),
      ).toContainText(["Versions", "Pin to sidebar", "Full screen"]);
      await page.getByRole("menuitem", { name: "Versions" }).click();
      await expect(page.getByTestId("artifact-versions")).toBeVisible();
      await shot(page, `phone-390-versions-${t}`);
      await page.keyboard.press("Escape");
      await page.setViewportSize({ width: 360, height: 800 });
      await page.waitForTimeout(300);
      await noSidewaysScroll(page);
    });
  }
});

for (const scheme of ["light", "dark"] as const) {
  test(`crossing Apps and Artifacts loads the destination document policy (${scheme})`, async ({
    page,
  }) => {
    await theme(page, scheme);
    await installFakeBridge(page, { pins: ["today"] });
    await installCodeStore(page, [budget()]);
    await page.goto("/workspace/apps/today");
    const appReady = async () => {
      await expect(
        page.frameLocator('[data-testid="app-frame"]').locator("body"),
      ).toHaveAttribute("data-rendered", "all");
      await expect(page.getByTestId("app-frame")).toHaveAttribute(
        "sandbox",
        "allow-scripts",
      );
    };
    await appReady();
    const navigate = async (link: Locator, apps: boolean) => {
      const response = page.waitForResponse(
        (r) =>
          r.request().isNavigationRequest() &&
          r.request().frame() === page.mainFrame(),
      );
      await link.click();
      const csp = (await response).headers()["content-security-policy"]!;
      const frameSrc = /frame-src ([^;]*)/.exec(csp)![1]!;
      expect(frameSrc.includes("/api/apps/")).toBe(apps);
      expect(frameSrc.includes("/api/artifacts/")).toBe(!apps);
    };
    await navigate(
      page.getByRole("link", { name: "Artifacts", exact: true }),
      false,
    );
    await page
      .getByRole("link", { name: "Budget Tracker", exact: true })
      .click();
    await expect(
      page
        .frameLocator('[data-testid="artifact-frame"]')
        .getByText("Spending by category", { exact: true }),
    ).toBeVisible();
    await expect(page.getByTestId("artifact-frame")).toHaveAttribute(
      "sandbox",
      "allow-scripts",
    );
    await navigate(page.getByTestId("pinned-app"), true);
    await appReady();
    await navigate(
      page.getByRole("link", { name: "Artifacts", exact: true }),
      false,
    );
    await page
      .getByRole("link", { name: "Budget Tracker", exact: true })
      .click();
    await expect(
      page
        .frameLocator('[data-testid="artifact-frame"]')
        .getByText("Spending by category", { exact: true }),
    ).toBeVisible();
  });
}
