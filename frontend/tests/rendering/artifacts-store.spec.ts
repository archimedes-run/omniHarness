import { mkdirSync } from "node:fs";
import { join } from "node:path";

import { expect, test, type Locator, type Page } from "@playwright/test";

import {
  IDS,
  installFakeStore,
  installThread,
  THREAD,
} from "./artifacts/fake-store";
import { lowContrastText } from "./contrast-probe";

/**
 * Spec 012 Slice 1 (frontend): inline artifact cards in the thread, the side
 * panel per static kind, versions (restore, owner edit with a stale base,
 * delete with a typed confirmation), and the Artifact store page, against
 * the fake store (tests/rendering/artifacts/fake-store.ts), whose fixtures
 * carry script, handlers and HTML in every kind.
 *
 * The inert-content checks, in every test that renders an artifact: no
 * payload ran (window.__canary stays unset), no element outside the allowed
 * set appears (no script, iframe, object, embed or foreignObject; no inline
 * SVG except the app's icons and the chart renderer's own), no element has
 * an on* attribute, and no request leaves this origin.
 *
 * ARTIFACT_SHOTS=<dir> saves screenshots (light, dark, 390 px).
 */

test.use({
  timezoneId: "UTC",
  // CHROMIUM_EXECUTABLE: a local browser build, when the bundled one is not
  // installed.
  launchOptions: {
    executablePath: process.env.CHROMIUM_EXECUTABLE ?? undefined,
  },
});

const SHOTS = process.env.ARTIFACT_SHOTS;
async function shot(page: Page, name: string) {
  if (!SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  await page.waitForTimeout(700); // the panel's slide-in
  await page.screenshot({ path: join(SHOTS, `${name}.png`) });
}

async function setup(
  page: Page,
  theme: "light" | "dark" = "light",
): Promise<{ outside: string[] }> {
  const outside: string[] = [];
  page.on("request", (req) => {
    const url = new URL(req.url());
    if (!/^https?:$/.test(url.protocol)) return;
    if (url.host !== "127.0.0.1:3000") outside.push(req.url());
  });
  await page.addInitScript((t) => {
    try {
      localStorage.setItem("theme", t);
    } catch {}
    // Any payload that runs calls this or sets the canary directly.
    (window as unknown as { x: () => void }).x = () => {
      (window as unknown as { __canary: number }).__canary = 1;
    };
  }, theme);
  return { outside };
}

async function assertInert(page: Page, outside: string[], scope?: Locator) {
  const root = scope ?? page.locator("body");
  expect(
    await page.evaluate(
      () => (window as unknown as { __canary?: number }).__canary,
    ),
  ).toBeUndefined();
  const bad = await root.evaluate((el) => {
    const out: string[] = [];
    for (const n of Array.from(
      el.querySelectorAll(
        "script, iframe, object, embed, foreignObject, frame, base, link[rel=import]",
      ),
    )) {
      if (n.closest("[data-testid^=artifact], [data-testid=mermaid-failed]")) {
        out.push(n.tagName);
      }
    }
    for (const svg of Array.from(el.querySelectorAll("svg"))) {
      if (!svg.closest("[data-testid^=artifact]")) continue;
      const ok =
        svg.classList.contains("lucide") ||
        svg.closest("[data-testid=artifact-chart]") !== null ||
        svg.closest(".cm-editor") !== null;
      if (!ok) out.push(`inline svg: ${svg.outerHTML.slice(0, 80)}`);
    }
    for (const n of Array.from(el.querySelectorAll("*"))) {
      for (const a of Array.from(n.attributes)) {
        if (/^on/i.test(a.name)) out.push(`${n.tagName} ${a.name}`);
      }
      if (n instanceof HTMLAnchorElement && /^\s*javascript:/i.test(n.href)) {
        out.push("javascript: link");
      }
    }
    return out;
  });
  expect(bad).toEqual([]);
  expect(outside).toEqual([]);
}

async function aa(page: Page) {
  const low = await page.evaluate(lowContrastText);
  expect(
    low,
    low.map((f) => `${f.ratio}/${f.need} "${f.text}" [${f.cls}]`).join("\n"),
  ).toEqual([]);
}

async function noHorizontalScroll(page: Page) {
  const over = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  );
  expect(over).toBeLessThanOrEqual(1);
}

async function openThread(page: Page) {
  await installThread(page);
  await page.goto(`/workspace/chats/${THREAD}`, { waitUntil: "networkidle" });
  await expect(page.getByTestId("artifact-card")).toHaveCount(8);
}

function card(page: Page, id: string, version = 1) {
  return page.locator(
    `[data-testid=artifact-card][data-artifact="${id}"][data-version="${version}"]`,
  );
}

async function openPanel(page: Page, id: string, version = 1) {
  await card(page, id, version).getByTestId("artifact-card-open").click();
  const panel = page.locator(
    `[data-testid=artifact-panel][data-artifact="${id}"]`,
  );
  await expect(panel).toBeVisible();
  return panel;
}

test.describe("the thread", () => {
  for (const theme of ["light", "dark"] as const) {
    test(`cards at the turns that made them, inert, AA (${theme})`, async ({
      page,
    }) => {
      await page.setViewportSize({ width: 1280, height: 900 });
      const { outside } = await setup(page, theme);
      await installFakeStore(page);
      await openThread(page);
      // The first turn's card keeps v1 and says a newer one exists; the
      // update's card shows "Version 2" of the same artifact.
      await expect(card(page, IDS.md, 1)).toContainText("v1");
      await expect(
        card(page, IDS.md, 1).getByTestId("artifact-card-latest"),
      ).toContainText("Latest: v2");
      await expect(
        card(page, IDS.md, 2).getByTestId("artifact-card-version"),
      ).toHaveText("Version 2");
      await expect(
        card(page, IDS.md, 2).getByTestId("artifact-card-lineage"),
      ).toHaveText("Made from content the assistant read (web_fetch)");
      await expect(
        card(page, IDS.md, 1).getByTestId("artifact-card-lineage"),
      ).toHaveCount(0);
      // Previews: chart as React SVG, svg and image as <img>, mermaid drawn.
      await expect(
        card(page, IDS.chart).getByTestId("artifact-chart"),
      ).toBeVisible();
      await expect(card(page, IDS.svg).locator("img")).toHaveAttribute(
        "src",
        `/api/artifacts/${IDS.svg}/versions/1/content`,
      );
      await expect(
        card(page, IDS.mermaid).getByTestId("artifact-mermaid"),
      ).toHaveAttribute("src", /^data:image\/svg\+xml;base64,/);
      await expect(
        card(page, IDS.broken).getByTestId("mermaid-failed"),
      ).toContainText("Couldn’t draw this diagram");
      // The title is text: markup in it shows as characters.
      await expect(card(page, IDS.chart).locator("h3")).toContainText(
        "<img src=x",
      );
      await card(page, IDS.image).scrollIntoViewIfNeeded();
      await assertInert(page, outside);
      await page.evaluate(() => window.scrollTo(0, 0));
      await card(page, IDS.md, 2).scrollIntoViewIfNeeded();
      await shot(page, `thread-cards-${theme}`);
      await aa(page);
    });
  }

  test("at 390 px the cards fit and a card opens full screen", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const { outside } = await setup(page, "light");
    await installFakeStore(page);
    await openThread(page);
    await noHorizontalScroll(page);
    await card(page, IDS.chart).scrollIntoViewIfNeeded();
    await shot(page, "thread-cards-390");
    await card(page, IDS.chart).getByTestId("artifact-card-open").click();
    const overlay = page.getByTestId("artifact-panel-mobile");
    await expect(overlay.getByTestId("artifact-chart")).toBeVisible();
    await noHorizontalScroll(page);
    await shot(page, "panel-chart-390");
    await assertInert(page, outside);
  });
});

test.describe("the side panel, per kind", () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
  });

  test("markdown: the safe renderer with raw HTML off", async ({ page }) => {
    const { outside } = await setup(page);
    await installFakeStore(page);
    await openThread(page);
    const panel = await openPanel(page, IDS.md, 2);
    const md = panel.getByTestId("artifact-markdown");
    await expect(md.locator("h1")).toHaveText("Project brief");
    await expect(md.locator("li")).toHaveCount(2);
    await expect(md.locator("img, iframe, script")).toHaveCount(0);
    await expect(panel.getByTestId("artifact-note")).toHaveText(
      "Shortened the title",
    );
    await expect(panel.getByTestId("artifact-lineage")).toBeVisible();
    await assertInert(page, outside, panel);
    await shot(page, "panel-markdown");
  });

  test("code: CodeMirror, read only, with its language", async ({ page }) => {
    const { outside } = await setup(page, "dark");
    await installFakeStore(page);
    await openThread(page);
    const panel = await openPanel(page, IDS.code);
    const code = panel.getByTestId("artifact-code");
    await expect(code).toHaveAttribute("data-language", "python");
    await expect(code.locator(".cm-content")).toContainText("def fizzbuzz");
    await expect(code.locator(".cm-content")).toHaveAttribute(
      "contenteditable",
      "false",
    );
    await assertInert(page, outside, panel);
    await shot(page, "panel-code-dark");
    await aa(page);
  });

  test("svg: only an <img> of the content route, never inline", async ({
    page,
  }) => {
    const { outside } = await setup(page);
    await installFakeStore(page);
    await openThread(page);
    const panel = await openPanel(page, IDS.svg);
    const img = panel.getByTestId("artifact-image");
    await expect(img).toHaveAttribute(
      "src",
      `/api/artifacts/${IDS.svg}/versions/1/content`,
    );
    await expect
      .poll(() => img.evaluate((i: HTMLImageElement) => i.naturalWidth))
      .toBeGreaterThan(0);
    await page.waitForTimeout(300);
    await assertInert(page, outside, panel);
    await shot(page, "panel-svg");
  });

  test("mermaid: drawn to an image; a label with HTML runs nothing; a broken one shows its source", async ({
    page,
  }) => {
    const { outside } = await setup(page);
    await installFakeStore(page);
    await openThread(page);
    const panel = await openPanel(page, IDS.mermaid);
    const img = panel.getByTestId("artifact-mermaid");
    await expect(img).toHaveAttribute("src", /^data:image\/svg\+xml;base64,/);
    await expect
      .poll(() => img.evaluate((i: HTMLImageElement) => i.naturalWidth))
      .toBeGreaterThan(0);
    // The offscreen drawing container is gone; no mermaid SVG in the page.
    expect(await page.locator("svg[id^=omni-mmd]").count()).toBe(0);
    await assertInert(page, outside);
    await shot(page, "panel-mermaid");
    const broken = await openPanel(page, IDS.broken);
    await expect(broken.getByTestId("mermaid-failed")).toContainText(
      "Couldn’t draw this diagram",
    );
    await expect(broken.locator(".cm-content")).toContainText("graph TD");
    await assertInert(page, outside);
  });

  for (const theme of ["light", "dark"] as const) {
    test(`chart: React SVG from the data spec, labels as text (${theme})`, async ({
      page,
    }) => {
      const { outside } = await setup(page, theme);
      await installFakeStore(page);
      await openThread(page);
      const panel = await openPanel(page, IDS.chart);
      const chart = panel.getByTestId("artifact-chart");
      await expect(chart.locator("rect")).toHaveCount(9); // one null skipped
      await expect(chart.locator("figcaption")).toContainText("<img src=x");
      await expect(chart.getByTestId("artifact-chart-legend")).toContainText(
        "Passed <script>",
      );
      // Tooltips are <title> elements.
      expect(await chart.locator("rect title").first().textContent()).toMatch(
        /Mon .*Passed .* 12 runs/,
      );
      await assertInert(page, outside, panel);
      await shot(page, `panel-chart-${theme}`);
      await aa(page);
    });
  }

  test("image: an <img> of the content route", async ({ page }) => {
    const { outside } = await setup(page);
    await installFakeStore(page);
    await openThread(page);
    const panel = await openPanel(page, IDS.image);
    await expect(panel.getByTestId("artifact-image")).toHaveAttribute(
      "src",
      `/api/artifacts/${IDS.image}/versions/1/content`,
    );
    await assertInert(page, outside, panel);
    await shot(page, "panel-image");
  });
});

test.describe("versions", () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
  });

  test("an older card opens its own version; Restore makes a new version", async ({
    page,
  }) => {
    await setup(page);
    const { log } = await installFakeStore(page);
    await openThread(page);
    const panel = await openPanel(page, IDS.md, 1);
    await expect(panel).toHaveAttribute("data-version", "1");
    await expect(panel.getByTestId("artifact-version-label")).toContainText(
      "Version 1 (latest: 2)",
    );
    await panel.getByTestId("artifact-versions-toggle").click();
    const v1 = panel.locator(
      "[data-testid=artifact-versions] li[data-version='1']",
    );
    await v1.getByTestId("artifact-version-restore").click();
    await expect(panel).toHaveAttribute("data-version", "3");
    expect(log.writes).toEqual([
      {
        method: "POST",
        path: `/api/artifacts/${IDS.md}/restore`,
        body: { version: 1, base_version: 2 },
      },
    ]);
    await expect(panel.getByRole("status")).toContainText(
      "Restored version 1 as version 3",
    );
  });

  test("an owner edit on a stale base says a newer version exists, and reloads", async ({
    page,
  }) => {
    await setup(page);
    const { log } = await installFakeStore(page, { staleOnce: true });
    await page.goto(`/workspace/artifacts/${IDS.md}`, {
      waitUntil: "networkidle",
    });
    await page.getByTestId("artifact-edit").click();
    const draft = page.getByTestId("artifact-draft");
    await expect(draft).toHaveValue(/Project brief/);
    await draft.fill("# A new brief");
    await page.getByTestId("artifact-save").click();
    await expect(page.getByTestId("artifact-stale")).toContainText(
      "A newer version exists",
    );
    // Nothing of ours was written; the draft is kept.
    await expect(draft).toHaveValue("# A new brief");
    await page.getByTestId("artifact-stale-reload").click();
    await expect(page.getByTestId("artifact-stale")).toHaveCount(0);
    await page.getByTestId("artifact-save").click();
    await expect(page.getByTestId("artifact-panel")).toHaveAttribute(
      "data-version",
      "4",
    );
    const saves = log.writes.filter((w) => w.path.endsWith("/versions"));
    expect(
      saves.map((w) => (w.body as { base_version: number }).base_version),
    ).toEqual([2, 3]);
  });

  test("delete only from the archive, after typing the title", async ({
    page,
  }) => {
    await setup(page);
    const { log } = await installFakeStore(page);
    await page.goto(`/workspace/artifacts/${IDS.md}`, {
      waitUntil: "networkidle",
    });
    await expect(page.getByTestId("artifact-delete")).toHaveCount(0);
    await page.goto(`/workspace/artifacts/${IDS.archived}`, {
      waitUntil: "networkidle",
    });
    const title = page.getByTestId("artifact-title");
    await expect(title).toHaveAttribute("title", /^Old notes with a very long/);
    await page.getByTestId("artifact-delete").click();
    const dialog = page.getByTestId("artifact-delete-dialog");
    await expect(dialog).toContainText("3 versions");
    const confirm = dialog.getByTestId("artifact-delete-confirm");
    await expect(confirm).toBeDisabled();
    await dialog.getByTestId("artifact-delete-input").fill("Old notes");
    await expect(confirm).toBeDisabled();
    await dialog
      .getByTestId("artifact-delete-input")
      .fill(`Old notes ${"with a very long title ".repeat(4)}`.trim());
    await confirm.click();
    await expect.poll(() => log.writes.length).toBe(1);
    expect(log.writes[0]).toEqual({
      method: "POST",
      path: `/api/artifacts/${IDS.archived}/delete`,
      body: { confirm_id: IDS.archived, version_count: 3 },
    });
  });
});

test.describe("the store page", () => {
  for (const theme of ["light", "dark"] as const) {
    test(`grid, filters, search, usage; AA (${theme})`, async ({ page }) => {
      await page.setViewportSize({ width: 1280, height: 900 });
      const { outside } = await setup(page, theme);
      const { log } = await installFakeStore(page);
      await page.goto("/workspace/artifacts", { waitUntil: "networkidle" });
      const cards = page.getByTestId("artifact-store-card");
      await expect(cards).toHaveCount(8);
      await expect(page.getByTestId("artifact-usage")).toContainText(
        "51 KB of 1.00 GB used",
      );
      // Pinned first.
      await expect(cards.first()).toHaveAttribute("data-artifact", IDS.md);
      // A file too large to import is a link to its chat.
      const big = page.locator(`[data-artifact="${IDS.big}"]`);
      await expect(big.getByTestId("artifact-store-card-link")).toHaveAttribute(
        "href",
        `/workspace/chats/${THREAD}`,
      );
      await page.waitForTimeout(400);
      await assertInert(page, outside);
      await shot(page, `store-${theme}`);
      await aa(page);
      await page.getByTestId("artifact-kind-chart").click();
      await expect(cards).toHaveCount(1);
      expect(log.gets.some((g) => g.includes("kind=chart"))).toBe(true);
      await page.getByTestId("artifact-kind-all").click();
      await page.getByTestId("artifact-search").fill("brief");
      await expect(cards).toHaveCount(1);
      expect(log.gets.some((g) => g.includes("q=brief"))).toBe(true);
      await page.getByTestId("artifact-search").fill("");
      await page.getByTestId("artifact-view-archived").click();
      await expect(cards).toHaveCount(1);
      await expect(cards.first()).toHaveAttribute(
        "data-artifact",
        IDS.archived,
      );
      await page.getByTestId("artifact-view-chat").click();
      await expect(page.getByTestId("artifact-by-chat")).toBeVisible();
    });
  }

  test("390 px: one column, no horizontal scroll; a card opens the full page", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const { outside } = await setup(page, "dark");
    await installFakeStore(page);
    await page.goto("/workspace/artifacts", { waitUntil: "networkidle" });
    await expect(page.getByTestId("artifact-store-card")).toHaveCount(8);
    await noHorizontalScroll(page);
    await shot(page, "store-390-dark");
    await page
      .locator(`[data-artifact="${IDS.chart}"]`)
      .getByTestId("artifact-store-card-link")
      .click();
    await expect(page).toHaveURL(
      new RegExp(`/workspace/artifacts/${IDS.chart}`),
    );
    await expect(page.getByTestId("artifact-chart")).toBeVisible();
    await expect(page.getByTestId("artifact-open-chat")).toHaveAttribute(
      "href",
      `/workspace/chats/${THREAD}`,
    );
    await noHorizontalScroll(page);
    await shot(page, "page-chart-390-dark");
    await assertInert(page, outside);
    await aa(page);
  });

  test("empty store: the empty state", async ({ page }) => {
    await setup(page);
    await installFakeStore(page, { empty: true });
    await page.goto("/workspace/artifacts", { waitUntil: "networkidle" });
    await expect(page.getByTestId("artifacts-empty")).toBeVisible();
  });

  test("routes missing (backend not merged): quiet, one request, no retries", async ({
    page,
  }) => {
    await setup(page);
    const { log } = await installFakeStore(page, { missing: true });
    await page.goto("/workspace/artifacts", { waitUntil: "networkidle" });
    await expect(page.getByTestId("artifacts-unavailable")).toBeVisible();
    await page.waitForTimeout(1500);
    expect(
      log.gets.filter((g) => g.startsWith("/api/artifacts?")),
    ).toHaveLength(1);
    expect(
      log.gets.filter((g) => g.startsWith("/api/artifacts/usage")),
    ).toHaveLength(0);
    // The thread: a card whose artifact cannot be read says so, once.
    await installThread(page);
    await page.goto(`/workspace/chats/${THREAD}`, { waitUntil: "networkidle" });
    await expect(page.getByTestId("artifact-card")).toHaveCount(8);
    await expect(page.getByTestId("artifact-card").first()).toContainText(
      "isn’t available",
    );
    await page.waitForTimeout(1500);
    const reads = log.gets.filter((g) => g === `/api/artifacts/${IDS.md}`);
    expect(reads).toHaveLength(1);
  });
});
