import { mkdirSync } from "node:fs";
import { join } from "node:path";

import { expect, test, type Locator, type Page } from "@playwright/test";

import {
  IDS,
  installFakeStore,
  installThread,
  SAVED_IDS,
  THREAD,
  threadState,
} from "./artifacts/fake-store";
import { lowContrastText } from "./contrast-probe";

/**
 * Spec 012, the owner's save model (api.md "Saved and unsaved"): nothing
 * lands in the store by itself. Every artifact has Save (then "Saved", with
 * Unsave in its menu) and Download (the gateway's download route); the
 * store opens on Saved, with an All tab; "Artifacts still in their chats"
 * lists what is not saved, by chat, each with Save; an artifact from a
 * deleted chat is labelled and still opens; a chat file or a static site is
 * saved with "Save to artifacts"; the store renders every kind, html and
 * webapp in the real LockedFrame (fake-code.ts serves the gateway's own
 * shim and profile).
 *
 * SAVED_SHOTS=<dir> saves screenshots (light, dark, 1280 and 390 px).
 */

test.use({
  timezoneId: "UTC",
  launchOptions: {
    executablePath: process.env.CHROMIUM_EXECUTABLE ?? undefined,
  },
});

const SHOTS = process.env.SAVED_SHOTS;
async function shot(page: Page, name: string) {
  if (!SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  await page.waitForTimeout(700);
  await page.screenshot({ path: join(SHOTS, `${name}.png`) });
}

async function setup(page: Page, theme: "light" | "dark" = "light") {
  await page.addInitScript((t) => {
    try {
      localStorage.setItem("theme", t);
    } catch {}
  }, theme);
}

async function aa(page: Page) {
  const low = await page.evaluate(lowContrastText);
  expect(
    low,
    low.map((f) => `${f.ratio}/${f.need} "${f.text}" [${f.cls}]`).join("\n"),
  ).toEqual([]);
}

async function noHorizontalScroll(page: Page) {
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    ),
  ).toBeLessThanOrEqual(1);
}

const card = (page: Page, id: string, version = 1) =>
  page.locator(
    `[data-testid=artifact-card][data-artifact="${id}"][data-version="${version}"]`,
  );
const storeCard = (page: Page, id: string) =>
  page.locator(`[data-testid=artifact-store-card][data-artifact="${id}"]`);

/** Saved in the "on" fixtures: the brief, the chart, two files, the notes
 * from a deleted chat, the html page and the web app. */
const SAVED_COUNT = 7;

test.describe("the store opens on Saved", () => {
  for (const theme of ["light", "dark"] as const) {
    test(`Saved by default, with an All tab; code kinds preview as a screenshot or an icon (${theme})`, async ({
      page,
    }) => {
      await page.setViewportSize({ width: 1280, height: 900 });
      await setup(page, theme);
      const { log } = await installFakeStore(page, { saving: "on" });
      await page.goto("/workspace/artifacts", { waitUntil: "networkidle" });
      await expect(page.getByTestId("artifact-view-saved")).toHaveAttribute(
        "aria-pressed",
        "true",
      );
      // The API's default is `all`: the Saved tab must ask for saved=true.
      expect(log.gets.some((g) => /[?&]saved=true(&|$)/.test(g))).toBe(true);
      const cards = page.getByTestId("artifact-store-card");
      await expect(cards).toHaveCount(SAVED_COUNT);
      await expect(storeCard(page, SAVED_IDS.react)).toHaveCount(0);
      await expect(
        storeCard(page, SAVED_IDS.html).getByTestId("artifact-shot"),
      ).toBeVisible();
      await expect(
        storeCard(page, SAVED_IDS.webapp).getByTestId("artifact-shot-icon"),
      ).toBeVisible();
      await expect(page.locator("iframe")).toHaveCount(0);
      // Save and Download on every card.
      for (const c of await cards.all()) {
        await expect(c.getByTestId("artifact-store-saved")).toBeVisible();
      }
      await expect(
        storeCard(page, IDS.md).getByTestId("artifact-store-download"),
      ).toHaveAttribute("href", `/api/artifacts/${IDS.md}/versions/2/download`);
      await expect(
        storeCard(page, SAVED_IDS.webapp).getByTestId(
          "artifact-store-download",
        ),
      ).toHaveAttribute(
        "href",
        `/api/artifacts/${SAVED_IDS.webapp}/versions/1/download`,
      );
      // An artifact from a deleted chat: labelled, no link to the chat.
      const orphan = storeCard(page, SAVED_IDS.orphan);
      await expect(
        orphan.getByTestId("artifact-store-origin-deleted"),
      ).toHaveText("From a chat you deleted");
      await expect(orphan.getByTestId("artifact-store-open-chat")).toHaveCount(
        0,
      );
      await expect(page.getByTestId("artifact-usage")).toBeVisible();
      await shot(page, `store-saved-${theme}-1280`);
      await aa(page);

      await page.getByTestId("artifact-view-all").click();
      await expect(page.getByTestId("artifact-view-all")).toHaveAttribute(
        "aria-pressed",
        "true",
      );
      expect(log.gets.some((g) => /[?&]saved=all(&|$)/.test(g))).toBe(true);
      // Every live artifact, saved or not (archived ones on their own tab).
      await expect(cards).toHaveCount(14);
      await expect(
        storeCard(page, SAVED_IDS.react).getByTestId("artifact-store-save"),
      ).toBeVisible();
    });
  }

  for (const width of [360, 390]) {
    for (const theme of ["light", "dark"] as const) {
      test(`${width} px (${theme}): no sideways scroll`, async ({ page }) => {
        await page.setViewportSize({ width, height: 844 });
        await setup(page, theme);
        await installFakeStore(page, { saving: "on" });
        await page.goto("/workspace/artifacts", { waitUntil: "networkidle" });
        await expect(page.getByTestId("artifact-store-card")).toHaveCount(
          SAVED_COUNT,
        );
        await noHorizontalScroll(page);
        if (width === 390) await shot(page, `store-saved-${theme}-390`);
      });
    }
  }

  test("nothing saved: the empty state says how to save", async ({ page }) => {
    await setup(page);
    await installFakeStore(page, { saving: "on", empty: true });
    await page.goto("/workspace/artifacts", { waitUntil: "networkidle" });
    await expect(page.getByTestId("artifacts-empty")).toContainText(
      "Nothing saved yet. Press Save on any artifact in a chat to keep it here.",
    );
    await page.getByTestId("artifact-view-unsaved").click();
    await expect(page.getByTestId("artifacts-unsaved-empty")).toBeVisible();
    await page.getByTestId("artifact-view-all").click();
    await expect(page.getByTestId("artifacts-empty")).toContainText(
      "No artifacts yet",
    );
    await page.getByTestId("artifact-view-pinned").click();
    await expect(page.getByTestId("artifacts-none-match")).toBeVisible();
  });

  test("Artifacts still in their chats: unsaved ones by chat, each with Save", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    await setup(page);
    const { log } = await installFakeStore(page, { saving: "on" });
    await page.goto("/workspace/artifacts", { waitUntil: "networkidle" });
    await page.getByTestId("artifact-view-unsaved").click();
    await expect(
      page.getByTestId("artifact-unsaved-group").first(),
    ).toBeVisible();
    expect(log.gets.some((g) => /[?&]saved=false(&|$)/.test(g))).toBe(true);
    const code = storeCard(page, IDS.code);
    await code.getByTestId("artifact-store-save").click();
    // Optimistic: "Saved" at once.
    await expect(code.getByTestId("artifact-store-saved")).toBeVisible();
    expect(log.writes).toContainEqual({
      method: "POST",
      path: `/api/artifacts/${IDS.code}/save`,
      body: null,
    });
    await aa(page);
  });
});

test.describe("Save and Download on every artifact", () => {
  test("cards in the chat: Save toggles to Saved with Unsave in its menu; Download is the download route", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    await setup(page);
    const { log } = await installFakeStore(page, { saving: "on" });
    await installThread(page);
    await page.goto(`/workspace/chats/${THREAD}`, { waitUntil: "networkidle" });
    const svg = card(page, IDS.svg);
    await expect(svg.getByTestId("artifact-store-download")).toHaveAttribute(
      "href",
      `/api/artifacts/${IDS.svg}/versions/1/download`,
    );
    await svg.getByTestId("artifact-store-save").click();
    await expect(svg.getByTestId("artifact-store-saved")).toBeVisible();
    await svg.getByTestId("artifact-store-saved").click();
    await page.getByTestId("artifact-store-unsave").click();
    await expect(svg.getByTestId("artifact-store-save")).toBeVisible();
    expect(log.writes.map((w) => w.path)).toEqual([
      `/api/artifacts/${IDS.svg}/save`,
      `/api/artifacts/${IDS.svg}/unsave`,
    ]);
    await card(page, IDS.md, 2).scrollIntoViewIfNeeded();
    await expect(
      card(page, IDS.md, 2).getByTestId("artifact-store-saved"),
    ).toBeVisible();
    await aa(page);
  });

  test("a refused save rolls back", async ({ page }) => {
    await setup(page);
    await installFakeStore(page, { saving: "failing" });
    await installThread(page);
    await page.goto(`/workspace/chats/${THREAD}`, { waitUntil: "networkidle" });
    const svg = card(page, IDS.svg);
    await svg.getByTestId("artifact-store-save").click();
    await expect(svg.getByRole("alert")).toBeVisible();
    await expect(svg.getByTestId("artifact-store-save")).toBeVisible();
    await expect(svg.getByTestId("artifact-store-saved")).toHaveCount(0);
  });

  test("the viewer has them too; a code kind keeps ONE set of downloads (its own)", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    await setup(page, "dark");
    const { log } = await installFakeStore(page, { saving: "on" });
    await page.goto(`/workspace/artifacts/${IDS.md}`, {
      waitUntil: "networkidle",
    });
    const panel = page.getByTestId("artifact-panel");
    await expect(panel.getByTestId("artifact-store-saved")).toBeVisible();
    await expect(panel.getByTestId("artifact-download")).toHaveAttribute(
      "href",
      `/api/artifacts/${IDS.md}/versions/2/download`,
    );

    await page.goto(`/workspace/artifacts/${SAVED_IDS.react}`, {
      waitUntil: "networkidle",
    });
    await panel.getByTestId("artifact-store-save").click();
    await expect(panel.getByTestId("artifact-store-saved")).toBeVisible();
    expect(log.writes.map((w) => w.path)).toContain(
      `/api/artifacts/${SAVED_IDS.react}/save`,
    );
    // ONE Download control: the code kind's menu (page and source).
    await expect(panel.getByTestId("artifact-store-download")).toHaveCount(0);
    await expect(panel.getByTestId("artifact-store-download-menu")).toHaveCount(
      0,
    );
    await panel.getByTestId("artifact-download-menu").click();
    const forms = page.getByTestId("artifact-download-form");
    await expect(forms.nth(0)).toHaveAttribute(
      "href",
      `/api/artifacts/${SAVED_IDS.react}/versions/1/download`,
    );
    await expect(forms.nth(1)).toHaveAttribute(
      "href",
      `/api/artifacts/${SAVED_IDS.react}/versions/1/download?source=zip`,
    );
  });
});

/** The LockedFrame of this panel, as main mounts it (sandbox exactly
 * allow-scripts, a one-view token, the nonce and theme in the fragment). */
async function lockedFrame(panel: Locator, id: string, theme: string) {
  const frame = panel.locator('[data-testid="artifact-frame"]');
  await expect(frame).toBeVisible({ timeout: 15_000 });
  await expect(frame).toHaveAttribute("sandbox", "allow-scripts");
  await expect(frame).toHaveAttribute("referrerpolicy", "no-referrer");
  await expect(frame).toHaveAttribute(
    "src",
    new RegExp(
      `^/api/artifacts/${id}/versions/1/frame\\.html\\?t=tok-${id}(&path=[^#]+)?#n=[A-Za-z0-9_-]{16,}&t=${theme}$`,
    ),
  );
  return frame;
}

test.describe("code kinds run from the store exactly as in chat", () => {
  for (const theme of ["light", "dark"] as const) {
    for (const width of [1280, 390]) {
      test(`html: opened from the Saved grid, runs in the locked frame (${theme}, ${width} px)`, async ({
        page,
      }) => {
        await page.setViewportSize({ width, height: 900 });
        await setup(page, theme);
        const { codeLog } = await installFakeStore(page, { saving: "on" });
        await page.goto("/workspace/artifacts", { waitUntil: "networkidle" });
        await storeCard(page, SAVED_IDS.html)
          .getByTestId("artifact-store-card-link")
          .click();
        await expect(page).toHaveURL(
          new RegExp(`/workspace/artifacts/${SAVED_IDS.html}`),
        );
        const panel = page.locator(
          `[data-testid=artifact-panel][data-artifact="${SAVED_IDS.html}"]`,
        );
        await expect(panel.getByTestId("artifact-check")).toContainText(
          "Checked",
        );
        const frame = await lockedFrame(panel, SAVED_IDS.html, theme);
        const inner = (await (await frame.elementHandle())!.contentFrame())!;
        await expect(inner.locator("h1")).toHaveText("Tip calculator");
        // One view: one token, one document from the frame route.
        expect(codeLog.frames.map((f) => f.path)).toEqual([
          `/api/artifacts/${SAVED_IDS.html}/versions/1/frame.html?t=tok-${SAVED_IDS.html}`,
        ]);
        await expect(panel.getByTestId("artifact-store-saved")).toBeVisible();
        await noHorizontalScroll(page);
        await aa(page);
        await shot(page, `store-html-${theme}-${width}`);
      });

      test(`webapp: its page list switches pages in the locked frame (${theme}, ${width} px)`, async ({
        page,
      }) => {
        await page.setViewportSize({ width, height: 900 });
        await setup(page, theme);
        await installFakeStore(page, { saving: "on" });
        await page.goto(`/workspace/artifacts/${SAVED_IDS.webapp}`, {
          waitUntil: "networkidle",
        });
        const panel = page.locator(
          `[data-testid=artifact-panel][data-artifact="${SAVED_IDS.webapp}"]`,
        );
        await expect(panel.getByTestId("artifact-check")).toContainText(
          "Not checked",
        );
        let frame = await lockedFrame(panel, SAVED_IDS.webapp, theme);
        let inner = (await (await frame.elementHandle())!.contentFrame())!;
        await expect(inner.locator("h1")).toHaveText("Site home");
        await panel
          .getByTestId("artifact-webapp-pages")
          .getByRole("button", { name: "about.html" })
          .click();
        await expect(frame).toHaveAttribute("src", /&path=about\.html#n=/);
        frame = await lockedFrame(panel, SAVED_IDS.webapp, theme);
        inner = (await (await frame.elementHandle())!.contentFrame())!;
        await expect(inner.locator("h1")).toHaveText("About this site");
        // One download: the file set as a .zip.
        await expect(panel.getByTestId("artifact-download")).toHaveAttribute(
          "href",
          `/api/artifacts/${SAVED_IDS.webapp}/versions/1/download`,
        );
        await expect(panel.getByTestId("artifact-store-download")).toHaveCount(
          0,
        );
        await noHorizontalScroll(page);
        await aa(page);
        await shot(page, `store-webapp-${theme}-${width}`);
      });
    }
  }
});

test.describe("static kinds render in the store", () => {
  test("markdown, code, svg, chart, image; files: text as text, others a Download to view card", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    await setup(page, "dark");
    await installFakeStore(page, { saving: "on" });
    const open = (id: string) =>
      page.goto(`/workspace/artifacts/${id}`, { waitUntil: "networkidle" });
    await open(IDS.md);
    await expect(page.getByTestId("artifact-markdown")).toContainText(
      "Project brief",
    );
    await open(IDS.code);
    await expect(
      page.getByTestId("artifact-code").locator(".cm-content"),
    ).toContainText("def fizzbuzz");
    await open(IDS.svg);
    await expect(page.getByTestId("artifact-image")).toHaveAttribute(
      "src",
      `/api/artifacts/${IDS.svg}/versions/1/content`,
    );
    await open(IDS.chart);
    await expect(page.getByTestId("artifact-chart")).toBeVisible();
    await open(IDS.image);
    await expect(page.getByTestId("artifact-image")).toHaveAttribute(
      "src",
      `/api/artifacts/${IDS.image}/versions/1/content`,
    );
    await open(SAVED_IDS.csv);
    await expect(
      page.getByTestId("artifact-code").locator(".cm-content"),
    ).toContainText("<script>");
    await expect(
      page.locator("[data-testid=artifact-panel] script"),
    ).toHaveCount(0);
    await open(SAVED_IDS.zip);
    await expect(page.getByTestId("artifact-download-to-view")).toContainText(
      "Download to view",
    );
    await aa(page);
  });

  // Needs the `mermaid` package (present in CI).
  test("mermaid: drawn to an image", async ({ page }) => {
    await setup(page);
    await installFakeStore(page, { saving: "on" });
    await page.goto(`/workspace/artifacts/${IDS.mermaid}`, {
      waitUntil: "networkidle",
    });
    // The testid is the <img> itself: the diagram drawn in its frame.
    await expect(page.getByTestId("artifact-mermaid")).toHaveAttribute(
      "src",
      /^data:image\/svg\+xml;base64,/,
      { timeout: 20_000 },
    );
  });

  test("an artifact from a deleted chat opens, labelled, with no chat link", async ({
    page,
  }) => {
    await setup(page);
    await installFakeStore(page, { saving: "on" });
    await page.goto("/workspace/artifacts", { waitUntil: "networkidle" });
    await storeCard(page, SAVED_IDS.orphan)
      .getByTestId("artifact-store-card-link")
      .click();
    const panel = page.getByTestId("artifact-panel");
    await expect(panel.getByTestId("artifact-markdown")).toContainText(
      "Kept after the chat was deleted.",
    );
    await expect(panel.getByTestId("artifact-origin-deleted")).toHaveText(
      "From a chat you deleted",
    );
    await expect(panel.getByTestId("artifact-open-chat")).toHaveCount(0);
  });
});

/** A chat whose turn presented a file and a static site. */
async function installFilesThread(page: Page) {
  const state = threadState();
  const messages = state.values.messages as unknown[];
  messages.push(
    { type: "human", id: "hf", content: "Export the scores." },
    {
      type: "ai",
      id: "af",
      content: "Here is the file and the site.",
      tool_calls: [
        {
          id: "pf",
          name: "present_files",
          args: {
            filepaths: [
              "/mnt/user-data/outputs/scores.csv",
              "/mnt/user-data/outputs/site/index.html",
            ],
          },
        },
      ],
    },
  );
  const json = (body: unknown) => ({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
  await installThread(page);
  await page.route("**/api/langgraph/**", (route) => {
    const url = route.request().url();
    if (url.includes("/history")) return route.fulfill(json([state]));
    if (url.includes("/runs") || url.includes("/search"))
      return route.fulfill(json([]));
    return route.fulfill(json(state));
  });
  await page.route("**/api/threads/*/artifacts/manifests", (route) =>
    route.fulfill(
      json({
        manifests: [
          {
            id: "site",
            title: "Site",
            type: "static_site",
            entrypoint: "index.html",
            root: ".",
            preview: { mode: "static" },
            manifest_path: "/mnt/user-data/outputs/site/artifact_manifest.json",
            root_path: "/mnt/user-data/outputs/site",
            entrypoint_path: "/mnt/user-data/outputs/site/index.html",
          },
        ],
      }),
    ),
  );
}

test.describe("Save to artifacts (chat outputs)", () => {
  test("a presented file is saved as itself and a static site as its directory, on the owner's press", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    await setup(page);
    const { log } = await installFakeStore(page, { saving: "on" });
    await installFilesThread(page);
    await page.goto(`/workspace/chats/${THREAD}`, { waitUntil: "networkidle" });
    // The files list shows in the message (and again in the side panel):
    // press each once, in the message's list.
    const fileCard = (name: string) =>
      page
        .locator('[data-slot="card"]', {
          has: page.getByText(name, { exact: true }),
        })
        .first();
    const csv = fileCard("scores.csv");
    const site = fileCard("Site");
    await expect(csv.getByTestId("save-to-artifacts")).toBeVisible();
    await expect(site.getByTestId("save-to-artifacts")).toBeVisible();
    // An icon button in the files list (the name keeps its room), named.
    await expect(csv.getByTestId("save-to-artifacts")).toHaveAccessibleName(
      "Save to artifacts",
    );
    expect(log.writes).toEqual([]);
    await csv.getByTestId("save-to-artifacts").click();
    const done = csv.getByTestId("save-to-artifacts-done");
    await expect(done).toHaveText("Saved. Open in Artifacts");
    await expect(done).toHaveAttribute(
      "href",
      /^\/workspace\/artifacts\/Imported/,
    );
    await site.getByTestId("save-to-artifacts").click();
    await expect(site.getByTestId("save-to-artifacts-done")).toBeVisible();
    expect(log.writes.map((w) => w.body)).toEqual([
      { thread_id: THREAD, path: "/mnt/user-data/outputs/scores.csv" },
      { thread_id: THREAD, path: "/mnt/user-data/outputs/site" },
    ]);
  });
});
