import { mkdirSync } from "node:fs";
import { join } from "node:path";

import { expect, test, type Page } from "@playwright/test";

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
 * Spec 012, the owner's correction: nothing lands in the store by itself.
 * Every artifact has Save (then "Saved", with Unsave in its menu) and
 * Download; the store opens on Saved; "Artifacts still in their chats"
 * lists what is not saved, by chat, each with Save; a chat file or a coding
 * job's site is saved with "Save to artifacts"; the store renders every
 * kind (files by media type, programs in the locked frame). On a gateway
 * without the save routes, the controls stay hidden after one 404.
 *
 * SAVED_SHOTS=<dir> saves screenshots (light, dark, 390 px).
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
  await page.waitForTimeout(600);
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

test.describe("the store opens on Saved", () => {
  for (const theme of ["light", "dark"] as const) {
    test(`Saved by default; code kinds preview as a screenshot or an icon, never a frame (${theme})`, async ({
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
      expect(log.gets.some((g) => g.includes("saved=true"))).toBe(true);
      const cards = page.getByTestId("artifact-store-card");
      await expect(cards).toHaveCount(6);
      for (const gone of ["all", "chat"]) {
        await expect(page.getByTestId(`artifact-view-${gone}`)).toHaveCount(0);
      }
      const html = page.locator(`[data-artifact="${SAVED_IDS.html}"]`);
      await expect(html.getByTestId("artifact-code-shot")).toBeVisible();
      await expect(
        page.locator("iframe[data-testid=artifact-frame]"),
      ).toHaveCount(0);
      await expect(
        page
          .locator(`[data-artifact="${IDS.md}"]`)
          .getByTestId("artifact-saved"),
      ).toBeVisible();
      await expect(page.getByTestId("artifact-usage")).toBeVisible();
      await shot(page, `store-saved-${theme}`);
      await aa(page);
    });
  }

  test("390 px: no sideways scroll", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await setup(page, "dark");
    await installFakeStore(page, { saving: "on" });
    await page.goto("/workspace/artifacts", { waitUntil: "networkidle" });
    await expect(page.getByTestId("artifact-store-card")).toHaveCount(6);
    await noHorizontalScroll(page);
    await shot(page, "store-saved-390-dark");
  });

  test("nothing saved: the empty state says how to save", async ({ page }) => {
    await setup(page);
    await installFakeStore(page, { saving: "on", empty: true });
    await page.goto("/workspace/artifacts", { waitUntil: "networkidle" });
    await expect(page.getByTestId("artifacts-empty")).toContainText(
      "Nothing saved yet. Press Save on any artifact in a chat to keep it here.",
    );
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
    expect(log.gets.some((g) => g.includes("saved=false"))).toBe(true);
    const code = page.locator(`[data-artifact="${IDS.code}"]`);
    await code.getByTestId("artifact-save").click();
    // Optimistic: "Saved" at once.
    await expect(code.getByTestId("artifact-saved")).toBeVisible();
    expect(log.writes).toContainEqual({
      method: "POST",
      path: `/api/artifacts/${IDS.code}/save`,
      body: null,
    });
    await shot(page, "store-unsaved-light");
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
    await expect(svg.getByTestId("artifact-download")).toHaveAttribute(
      "href",
      `/api/artifacts/${IDS.svg}/versions/1/download`,
    );
    await svg.getByTestId("artifact-save").click();
    await expect(svg.getByTestId("artifact-saved")).toBeVisible();
    await svg.getByTestId("artifact-saved").click();
    await page.getByTestId("artifact-unsave").click();
    await expect(svg.getByTestId("artifact-save")).toBeVisible();
    expect(log.writes.map((w) => w.path)).toEqual([
      `/api/artifacts/${IDS.svg}/save`,
      `/api/artifacts/${IDS.svg}/unsave`,
    ]);
    await card(page, IDS.md, 2).scrollIntoViewIfNeeded();
    await expect(
      card(page, IDS.md, 2).getByTestId("artifact-saved"),
    ).toBeVisible();
    await shot(page, "thread-save-light");
    await aa(page);
  });

  test("a refused save rolls back", async ({ page }) => {
    await setup(page);
    await installFakeStore(page, { saving: "failing" });
    await installThread(page);
    await page.goto(`/workspace/chats/${THREAD}`, { waitUntil: "networkidle" });
    const svg = card(page, IDS.svg);
    await svg.getByTestId("artifact-save").click();
    await expect(svg.getByRole("alert")).toBeVisible();
    await expect(svg.getByTestId("artifact-save")).toBeVisible();
    await expect(svg.getByTestId("artifact-saved")).toHaveCount(0);
  });

  test("the panel header has them too; react offers two download forms", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    await setup(page, "dark");
    await installFakeStore(page, { saving: "on" });
    await page.goto(`/workspace/artifacts/${SAVED_IDS.react}`, {
      waitUntil: "networkidle",
    });
    await expect(page.getByTestId("artifact-save")).toBeVisible();
    await page.getByTestId("artifact-download-menu").click();
    const forms = page.getByTestId("artifact-download-form");
    await expect(forms).toHaveCount(2);
    await expect(forms.nth(0)).toHaveText("Built page (.html)");
    await expect(forms.nth(0)).toHaveAttribute(
      "href",
      `/api/artifacts/${SAVED_IDS.react}/versions/1/download?form=built`,
    );
    await expect(forms.nth(1)).toHaveText("Source (.zip)");
    await shot(page, "page-react-download-dark");
  });
});

test.describe("rendering everything from the store", () => {
  test("html: in the locked frame, sandbox allow-scripts exactly; the page reaches nothing", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    await setup(page);
    const fromFrame: string[] = [];
    page.on("response", (res) => {
      if (res.request().frame() !== page.mainFrame()) {
        const path = new URL(res.url()).pathname;
        if (!path.endsWith("/frame.html")) fromFrame.push(path);
      }
    });
    await installFakeStore(page, { saving: "on" });
    await page.goto(`/workspace/artifacts/${SAVED_IDS.html}`, {
      waitUntil: "networkidle",
    });
    const frame = page.getByTestId("artifact-frame");
    await expect(frame).toHaveAttribute("sandbox", "allow-scripts");
    await expect(frame).toHaveAttribute(
      "src",
      new RegExp(
        `^/api/artifacts/${SAVED_IDS.html}/versions/1/frame\\.html\\?t=tok#n=[A-Za-z0-9_-]{16,}&t=light$`,
      ),
    );
    // The handshake ran (hello, init, ready, size) ...
    await expect(
      page.frameLocator("[data-testid=artifact-frame]").locator("#t"),
    ).toHaveText("Kanban board (ready)");
    await expect(frame).toHaveCSS("height", "320px");
    // ... and the page could not touch the app.
    expect(await page.title()).not.toBe("pwned");
    expect(
      await page.evaluate(
        () => (window as unknown as { __canary?: number }).__canary,
      ),
    ).toBeUndefined();
    expect(fromFrame).toEqual([]);
    await shot(page, "page-html-frame-light");
  });

  test("files: text as text, images as images, others a Download to view card", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    await setup(page, "dark");
    await installFakeStore(page, { saving: "on" });
    await page.goto(`/workspace/artifacts/${SAVED_IDS.csv}`, {
      waitUntil: "networkidle",
    });
    const code = page.getByTestId("artifact-code");
    await expect(code.locator(".cm-content")).toContainText("<script>");
    await expect(
      page.locator("[data-testid=artifact-panel] script"),
    ).toHaveCount(0);
    await shot(page, "page-file-text-dark");
    await page.goto(`/workspace/artifacts/${SAVED_IDS.png}`, {
      waitUntil: "networkidle",
    });
    await expect(page.getByTestId("artifact-image")).toHaveAttribute(
      "src",
      `/api/artifacts/${SAVED_IDS.png}/versions/1/content`,
    );
    await page.goto(`/workspace/artifacts/${SAVED_IDS.zip}`, {
      waitUntil: "networkidle",
    });
    await expect(page.getByTestId("artifact-download-to-view")).toContainText(
      "Download to view",
    );
    await aa(page);
  });
});

/** A chat whose turn presented a file (the existing files list). */
async function installFilesThread(page: Page) {
  const state = threadState();
  const messages = state.values.messages as unknown[];
  messages.push(
    { type: "human", id: "hf", content: "Export the scores." },
    {
      type: "ai",
      id: "af",
      content: "Here is the file.",
      tool_calls: [
        {
          id: "pf",
          name: "present_files",
          args: { filepaths: ["/mnt/user-data/outputs/scores.csv"] },
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
}

test.describe("Save to artifacts (chat files)", () => {
  test("a presented file is saved on the owner's press, then links to the store", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    await setup(page);
    const { log } = await installFakeStore(page, { saving: "on" });
    await installFilesThread(page);
    await page.goto(`/workspace/chats/${THREAD}`, { waitUntil: "networkidle" });
    const button = page.getByTestId("save-to-artifacts").first();
    await button.scrollIntoViewIfNeeded();
    expect(log.writes).toEqual([]);
    await button.click();
    const done = page.getByTestId("save-to-artifacts-done");
    await expect(done).toContainText("Saved ✓ — open in Artifacts");
    await expect(done).toHaveAttribute(
      "href",
      /^\/workspace\/artifacts\/Imported/,
    );
    expect(log.writes).toEqual([
      {
        method: "POST",
        path: "/api/artifacts/import",
        body: { thread_id: THREAD, path: "/mnt/user-data/outputs/scores.csv" },
      },
    ]);
    await shot(page, "thread-save-to-artifacts-light");
  });
});

test.describe("a gateway without the save routes", () => {
  test("Save and Download stay hidden; Save to artifacts hides after one 404; no retries", async ({
    page,
  }) => {
    await setup(page);
    const { log } = await installFakeStore(page, { saving: "missing" });
    await installFilesThread(page);
    await page.goto(`/workspace/chats/${THREAD}`, { waitUntil: "networkidle" });
    await expect(page.getByTestId("artifact-card").first()).toBeVisible();
    await expect(page.getByTestId("artifact-save-download")).toHaveCount(0);
    const button = page.getByTestId("save-to-artifacts").first();
    await button.scrollIntoViewIfNeeded();
    await button.click();
    await expect(page.getByTestId("save-to-artifacts")).toHaveCount(0);
    await page.waitForTimeout(1000);
    expect(
      log.writes.filter((w) => w.path === "/api/artifacts/import"),
    ).toHaveLength(1);
    await page.goto("/workspace/artifacts", { waitUntil: "networkidle" });
    await expect(page.getByTestId("artifact-store-card").first()).toBeVisible();
    await expect(page.getByTestId("artifact-save-download")).toHaveCount(0);
  });
});
