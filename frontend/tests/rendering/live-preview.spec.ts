import { expect, test, type Frame, type Page } from "@playwright/test";

import { installThread, THREAD, threadState } from "./artifacts/fake-store";
import {
  type App,
  installLivePreview,
  type LiveLog,
  OWNER_SECRET,
  PROFILE,
  REAL_GATEWAY,
} from "./live-preview/fake-live";

/**
 * The live preview of a web app built in a chat runs in a sandboxed frame:
 * an opaque origin, on a short-lived frame link (the gateway's
 * preview_frame.py): the app it runs shares nothing of this app's origin,
 * storage or session. What still works: the app's module scripts, styles, assets and
 * its own API; navigation between its pages; Restart; Open in new window
 * (also opaque).
 *
 * NO BACKEND by default (live-preview/fake-live.ts fakes the frame link from
 * the gateway's own header profile). With LIVE_PREVIEW_GATEWAY set, the frame
 * link is served by the real gateway code (live-preview/gateway_harness.py),
 * and the tests that need the gateway's page shim run too.
 *
 * LIVE_SABOTAGE (sabotage runs only, a comma list): "no-sandbox" strips the iframe's
 * sandbox attribute, "same-origin" adds allow-same-origin to it, "no-header"
 * drops the response sandbox header.
 */

test.use({
  launchOptions: {
    executablePath: process.env.CHROMIUM_EXECUTABLE ?? undefined,
  },
  viewport: { width: 1440, height: 900 },
});

const SABOTAGE = (process.env.LIVE_SABOTAGE ?? "").split(",");
const FRAME_SABOTAGE = SABOTAGE.find(
  (m) => m === "no-sandbox" || m === "same-origin",
);

// Loads still in flight when a test ends (a popup's fetches) are not failures.
test.afterEach(async ({ page }) => {
  await page.unrouteAll({ behavior: "ignoreErrors" });
  await page.context().unrouteAll({ behavior: "ignoreErrors" });
});

async function setup(page: Page, apps: App[], expiresInSeconds?: number) {
  await page.context().addCookies([
    {
      name: "access_token",
      value: "owner-session",
      domain: "127.0.0.1",
      path: "/",
      httpOnly: true,
      sameSite: "Lax",
    },
    {
      name: "csrf_token",
      value: "csrf-owner",
      domain: "127.0.0.1",
      path: "/",
      sameSite: "Strict",
    },
  ]);
  await installThread(page);
  const state = threadState();
  (state.values.messages as unknown[]).push(
    { type: "human", id: "hl", content: "Build me the app and run it." },
    {
      type: "ai",
      id: "al",
      content: "It is running.",
      tool_calls: [
        {
          id: "pl",
          name: "present_files",
          args: {
            filepaths: apps.map(
              (app) => `/mnt/user-data/outputs/${app}/artifact_manifest.json`,
            ),
          },
        },
      ],
    },
  );
  await page.route("**/api/langgraph/**", (route) => {
    const url = route.request().url();
    const body = (b: unknown) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(b),
      });
    if (url.includes("/history")) return body([state]);
    if (url.includes("/runs") || url.includes("/search")) return body([]);
    return body(state);
  });
  const log = await installLivePreview(page, {
    thread: THREAD,
    apps,
    expiresInSeconds,
  });
  if (FRAME_SABOTAGE) {
    await page.addInitScript((mode) => {
      new MutationObserver(() => {
        const f = document.querySelector(
          'iframe[title^="Live "]:not([data-sabotaged])',
        );
        if (!f) return;
        f.setAttribute("data-sabotaged", "1");
        if (mode === "no-sandbox") f.removeAttribute("sandbox");
        else
          f.setAttribute(
            "sandbox",
            `${f.getAttribute("sandbox") ?? ""} allow-same-origin`,
          );
        // A sandbox change applies on the next navigation: reload it.
        const src = f.getAttribute("src")!;
        f.setAttribute("src", `${src}${src.includes("?") ? "&" : "?"}reload=1`);
      }).observe(document, { childList: true, subtree: true });
    }, FRAME_SABOTAGE);
  }
  return log;
}

async function openPreview(page: Page, app: App): Promise<Frame> {
  await page.goto(`/workspace/chats/${THREAD}`, { waitUntil: "networkidle" });
  await page
    .locator('[data-slot="card"]', {
      has: page.getByText(`Live ${app}`, { exact: true }),
    })
    .first()
    .click();
  // The Preview toggle (its eye icon: the same on builds before it was named).
  await page
    .locator("[role=radio]")
    .filter({ has: page.locator("svg.lucide-eye") })
    .first()
    .click();
  await expect(liveFrame(page)).toBeVisible();
  return frameOf(page);
}

/** The panel's live preview iframe (titled with the app's name). */
const liveFrame = (page: Page) => page.locator('iframe[title^="Live "]');

async function frameOf(page: Page): Promise<Frame> {
  await expect
    .poll(() => page.frames().some((f) => f.url().includes("/previews/")))
    .toBe(true);
  return page.frames().find((f) => f.url().includes("/previews/"))!;
}

function liveRequestsBy(log: LiveLog, type: string) {
  return log.live.filter((r) => r.type === type);
}

test("the live preview runs in an opaque origin, apart from the app", async ({
  page,
}) => {
  const log = await setup(page, ["probe"]);
  await page.addInitScript(() => {
    window.addEventListener("message", (e) => {
      const d = e.data as { probe?: Record<string, string> };
      const w = window as unknown as { __probes?: unknown[] };
      if (d?.probe) (w.__probes ??= []).push(d.probe);
    });
  });
  await openPreview(page, "probe");
  const probes = () =>
    page.evaluate(
      () =>
        (window as unknown as { __probes?: Record<string, string>[] })
          .__probes ?? [],
    );
  await expect.poll(async () => (await probes()).length).toBeGreaterThan(0);
  await page.waitForTimeout(1500); // every document the frame ran reports
  for (const out of await probes()) {
    // The page runs (scripts are allowed), but cannot read the owner's API,
    // sees no cookie and cannot reach into the app ...
    expect(out.api ?? "").not.toContain(OWNER_SECRET);
    expect(out.cookie ?? "").not.toContain("csrf_token");
    expect(out.parent).toBe("blocked");
    // ... because its origin is opaque: the frame's sandbox.
    expect(out.origin).toBe("null");
    // Storage is the gateway's in-memory stand-in.
    expect(out.storage).toBe("function");
  }
  await expect(liveFrame(page)).toHaveAttribute("sandbox", PROFILE.sandbox);
  // The API request left without the session cookie.
  expect(log.probe.every((p) => !p.cookie)).toBe(true);
  // Every load the frame made itself carried no cookie either.
  const own = log.live.filter((r) => r.type !== "document");
  expect(own.every((r) => !r.cookie)).toBe(true);
});

test("a Vite-style app loads its modules, styles, assets and own API, and moves between its views", async ({
  page,
}) => {
  const log = await setup(page, ["vite-app"]);
  const frame = await openPreview(page, "vite-app");
  await expect(frame.locator("#title")).toHaveText("Counter");
  await expect(frame.locator("#title")).toHaveCSS("color", "rgb(1, 2, 3)");
  await expect
    .poll(() =>
      frame
        .locator("#logo")
        .evaluate((img: HTMLImageElement) => img.naturalWidth),
    )
    .toBeGreaterThan(0);
  await expect(frame.locator("#items li")).toHaveText(["alpha", "beta"]);
  await expect(frame.locator("#echo")).toHaveText("echo dev server");
  await frame.locator("#inc").click();
  await expect(frame.locator("#inc")).toHaveText("count is 1");
  // Its HMR client tried its websocket and carried on (no websocket proxy).
  await expect(frame.locator("meta[name=hmr]")).toHaveAttribute(
    "content",
    /failed|threw/,
  );
  // Client-side navigation between its own views.
  await frame.locator("#to-about").click();
  await expect(frame.locator("#about")).toHaveText("About this counter");
  await expect(frame.locator("#about")).toHaveCSS("color", "rgb(4, 5, 6)");
  if (REAL_GATEWAY)
    expect(new URL(frame.url()).pathname).toMatch(/\/live\/[^/]+\/about$/);
  await frame.locator("#to-home").click();
  await expect(frame.locator("#title")).toHaveText("Counter");
  await expect(frame.locator("#items li")).toHaveText(["alpha", "beta"]);
  await expect(frame.locator("#echo")).toHaveText("echo dev server");
  // Every module, style and image came over the frame link.
  for (const type of ["script", "stylesheet", "image"])
    expect(liveRequestsBy(log, type).length, type).toBeGreaterThan(0);
});

test("a static multi-page site served by a dev server navigates between its pages", async ({
  page,
}) => {
  const log = await setup(page, ["site"]);
  let frame = await openPreview(page, "site");
  await expect(frame.locator("#home-title")).toHaveText("Our studio");
  await expect(frame.locator("#home-title")).toHaveCSS(
    "color",
    "rgb(10, 20, 30)",
  );
  await frame.locator("#next").click();
  await expect
    .poll(() => page.frames().some((f) => f.url().endsWith("/about.html")))
    .toBe(true);
  frame = page.frames().find((f) => f.url().endsWith("/about.html"))!;
  await expect(frame.locator("#about-title")).toHaveText("About us");
  await expect(frame.locator("#about-title")).toHaveCSS(
    "color",
    "rgb(10, 20, 30)",
  );
  await frame.locator("#home").click();
  await expect
    .poll(() => page.frames().some((f) => f.url().endsWith("/index.html")))
    .toBe(true);
  const docs = liveRequestsBy(log, "document").map((r) => r.url);
  expect(docs.some((u) => u.endsWith("/about.html"))).toBe(true);
  expect(docs.some((u) => u.endsWith("/index.html"))).toBe(true);
});

test("Restart reloads the frame; Open in new window opens the app opaque to this origin", async ({
  page,
}) => {
  const log = await setup(page, ["probe", "vite-app"]);
  let frame = await openPreview(page, "vite-app");
  await expect(frame.locator("#title")).toHaveText("Counter");
  await page.getByRole("button", { name: "Restart preview" }).click();
  await expect.poll(() => log.restarts).toBe(1);
  frame = await frameOf(page);
  await expect(frame.locator("#title")).toHaveText("Counter");

  const [popup] = await Promise.all([
    page.context().waitForEvent("page"),
    page.getByRole("button", { name: "Open in new window" }).click(),
  ]);
  await popup.waitForLoadState();
  expect(new URL(popup.url()).pathname).toMatch(/\/live\/[^/]+\/?$/);
  await expect(popup.locator("#title")).toHaveText("Counter");
  await expect(popup.locator("#items li")).toHaveText(["alpha", "beta"]);
  expect(await popup.evaluate(() => self.origin)).toBe("null");
  const read = await popup.evaluate(async (secret) => {
    try {
      const r = await fetch(location.origin + "/api/v1/auth/me?probe=1", {
        credentials: "include",
      });
      return (await r.text()).includes(secret) ? "read" : "not read";
    } catch {
      return "blocked";
    }
  }, OWNER_SECRET);
  expect(read).not.toBe("read");
  await popup.close();
});

test("a fresh frame link reaches the running app without reloading it", async ({
  page,
}) => {
  const log = await setup(page, ["vite-app"], 12);
  const frame = await openPreview(page, "vite-app");
  await frame.locator("#inc").click();
  await expect(frame.locator("#inc")).toHaveText("count is 1");
  const first = log.minted[0]!;
  // Asked again at half its life (fake: 12 s, so about 6 s).
  await expect
    .poll(() => log.minted.length, { timeout: 15_000 })
    .toBeGreaterThan(1);
  const fresh = log.minted.at(-1)!;
  expect(fresh).not.toBe(first);
  await expect(frame.locator("#root-seen")).toHaveText(fresh);
  // Not reloaded: the frame keeps its first link and the app its state.
  await expect(liveFrame(page)).toHaveAttribute("src", first);
  await expect(frame.locator("#inc")).toHaveText("count is 1");
  if (REAL_GATEWAY) {
    // The gateway's page shim moved later loads to the fresh link.
    expect(
      await frame.evaluate(() =>
        document.querySelector("base[data-omni-preview]")!.getAttribute("href"),
      ),
    ).toBe(`${fresh}/`);
    const before = log.live.length;
    await frame.evaluate(() => fetch("/api/items.json").then((r) => r.json()));
    expect(log.live.slice(before).some((r) => fresh.endsWith(r.token))).toBe(
      true,
    );
  }
});
