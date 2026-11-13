import { mkdirSync } from "node:fs";
import { join } from "node:path";

import { expect, test, type Frame, type Page } from "@playwright/test";

import {
  demoApp,
  HASH_PENDING,
  installFakeBridge,
  pendingApp,
} from "./apps/fake-bridge";
import { lowContrastText } from "./contrast-probe";

/**
 * Spec 011 PR 2: the Apps library, the app host page and the sidebar pin,
 * against the fake bridge (tests/rendering/apps/fake-bridge.ts) and the demo
 * app (mock data). The attack suite is apps-attack.spec.ts; the warm-cache
 * timing is apps-perf.spec.ts.
 *
 * APPS_SHOTS=<dir> saves screenshots (light, dark, phone width).
 */

test.use({ timezoneId: "UTC" });

const SHOTS = process.env.APPS_SHOTS;
async function shot(page: Page, name: string) {
  if (!SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  await page.screenshot({ path: join(SHOTS, `${name}.png`), fullPage: false });
}

async function setTheme(page: Page, theme: "light" | "dark") {
  await page.addInitScript((t) => {
    try {
      localStorage.setItem("theme", t);
    } catch {}
  }, theme);
}

/** The app's frame, once its tiles have all rendered. */
async function appFrame(page: Page): Promise<Frame> {
  const handle = await page
    .locator('[data-testid="app-frame"]')
    .elementHandle();
  const frame = await handle!.contentFrame();
  await expect
    .poll(() => frame!.evaluate(() => document.body?.dataset.rendered ?? ""))
    .toBe("all");
  return frame!;
}

async function contrast(page: Page) {
  const found = await page.evaluate(lowContrastText);
  expect(
    found,
    found
      .map((f) => `${f.ratio}/${f.need} "${f.text}" ${f.color} [${f.cls}]`)
      .join("\n"),
  ).toEqual([]);
}

test.describe("the host page", () => {
  test("embeds the app with sandbox=allow-scripts exactly, and the page CSP frames only this origin", async ({
    page,
  }) => {
    await installFakeBridge(page);
    const response = await page.goto("/workspace/apps/today");
    const csp = response!.headers()["content-security-policy"] ?? "";
    expect(csp).toContain("frame-src 'self';");
    expect(csp).not.toMatch(/frame-src[^;]*blob:/);
    const frame = page.locator('[data-testid="app-frame"]');
    await expect(frame).toHaveAttribute("sandbox", "allow-scripts");
    await expect(frame).toHaveAttribute(
      "src",
      "/api/apps/today/versions/3/app.html",
    );
    await expect(frame).toHaveAttribute("referrerpolicy", "no-referrer");
    // The library route carries the same policy.
    const lib = await page.request.get("/workspace/apps");
    expect(lib.headers()["content-security-policy"]).toContain(
      "frame-src 'self';",
    );
  });

  test("every tile shows its data from the batch prefetch: one round trip", async ({
    page,
  }) => {
    const bridge = await installFakeBridge(page);
    await page.goto("/workspace/apps/today");
    const frame = await appFrame(page);
    for (const tile of ["calendar", "gh_review", "inbox", "ledger"]) {
      await expect(frame.locator(`[data-tile="${tile}"]`)).toHaveAttribute(
        "data-state",
        "fresh",
      );
    }
    await expect(frame.locator('[data-tile="calendar"]')).toContainText(
      "updated 4 min ago",
    );
    await expect(frame.locator('[data-tile="calendar"]')).toContainText(
      "Design review",
    );
    expect(bridge.log.dataReads).toEqual(["*"]);
  });

  test("all four tile states, worded the same way", async ({ page }) => {
    await installFakeBridge(page, {
      apps: [
        demoApp({
          states: {
            calendar: "fresh",
            gh_review: "empty",
            inbox: "not_connected",
            ledger: "failed",
          },
        }),
      ],
    });
    await page.goto("/workspace/apps/today");
    const frame = await appFrame(page);
    await expect(frame.locator('[data-tile="calendar"]')).toContainText(
      "updated 4 min ago",
    );
    await expect(frame.locator('[data-tile="gh_review"]')).toContainText(
      "Nothing today",
    );
    await expect(frame.locator('[data-tile="inbox"]')).toContainText(
      "Not connected",
    );
    await expect(frame.locator('[data-tile="ledger"]')).toContainText(
      "Can't tell · The connector did not answer in time.",
    );
  });

  test("Connect in a tile opens the host's own Connect sheet; the frame starts nothing", async ({
    page,
  }) => {
    const popups: string[] = [];
    page.on("popup", (p) => popups.push(p.url()));
    await installFakeBridge(page, {
      apps: [demoApp({ states: { inbox: "not_connected" } })],
    });
    await page.goto("/workspace/apps/today");
    const frame = await appFrame(page);
    await frame.locator('[data-connect="inbox"]').click();
    const sheet = page.getByTestId("app-connect-sheet");
    await expect(sheet).toBeVisible();
    await expect(sheet).toContainText("Connect Gmail");
    await expect(sheet).toContainText(
      "Read subjects of unread mail in Primary",
    );
    await expect(page.getByTestId("app-connect-button")).toBeVisible();
    expect(popups).toEqual([]);
  });

  test("the theme is passed in and follows the page live", async ({ page }) => {
    await setTheme(page, "light");
    await installFakeBridge(page);
    await page.goto("/workspace/apps/today");
    const frame = await appFrame(page);
    expect(
      await frame.evaluate(() =>
        document.documentElement.classList.contains("dark"),
      ),
    ).toBe(false);
    await page.evaluate(() => document.documentElement.classList.add("dark"));
    await expect
      .poll(() =>
        frame.evaluate(() =>
          document.documentElement.classList.contains("dark"),
        ),
      )
      .toBe(true);
    const log = (await frame.evaluate(
      () => (window as unknown as { __omniLog: unknown[] }).__omniLog,
    )) as {
      type: string;
      theme?: string;
    }[];
    expect(log[0]).toMatchObject({
      type: "init",
      app: "today",
      version: 3,
      theme: "light",
    });
    expect(log.some((m) => m.type === "theme" && m.theme === "dark")).toBe(
      true,
    );
  });

  test("a link in the app: allowed hosts open in a new tab, /workspace paths in place", async ({
    page,
    context,
  }) => {
    await installFakeBridge(page);
    // The new tab never reaches the real site.
    await context.route("https://github.com/**", (route) =>
      route.fulfill({
        status: 200,
        contentType: "text/html",
        body: "<p>stub</p>",
      }),
    );
    await page.goto("/workspace/apps/today");
    const frame = await appFrame(page);
    const popup = context.waitForEvent("page");
    await frame.getByRole("link", { name: "Fix the date picker" }).click();
    const tab = await popup;
    await tab.waitForURL(/github\.com\/acme\/web\/pull\/412/);
    // noopener: the new tab has no handle back to the host.
    expect(await tab.evaluate(() => window.opener === null)).toBe(true);
    await tab.close();
    await frame.getByRole("link", { name: "Write the release notes" }).click();
    await expect(page).toHaveURL(/\/workspace\/projects\/p1$/);
  });

  test("the frame reloading itself is torn down: no second handshake", async ({
    page,
  }) => {
    const bridge = await installFakeBridge(page);
    await page.goto("/workspace/apps/today");
    const frame = await appFrame(page);
    await frame.evaluate(() => location.reload());
    await expect(page.getByTestId("app-reloaded")).toBeVisible();
    await expect
      .poll(() => bridge.log.refused)
      .toEqual([{ reason: "second_load" }]);
    await expect(page.getByTestId("app-reloaded")).toContainText(
      "This app reloaded itself. Reopen it.",
    );
    await expect(page.locator('[data-testid="app-frame"]')).toHaveCount(0);
    await page.getByTestId("app-reopen").click();
    await appFrame(page);
  });

  test("Full screen restyles the same frame: it does not reload", async ({
    page,
  }) => {
    await installFakeBridge(page);
    await page.goto("/workspace/apps/today");
    const frame = await appFrame(page);
    await frame.evaluate(
      () => ((window as unknown as { __mark: number }).__mark = 42),
    );
    await page.getByTestId("app-fullscreen").click();
    await expect(page.getByTestId("app-host")).toHaveAttribute(
      "data-full",
      "true",
    );
    expect(
      await frame.evaluate(
        () => (window as unknown as { __mark: number }).__mark,
      ),
    ).toBe(42);
    await expect(page.getByTestId("app-reloaded")).toHaveCount(0);
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("app-host")).toHaveAttribute(
      "data-full",
      "false",
    );
  });

  test("an app that needs approval shows its card, never the frame; Allow is the only way", async ({
    page,
  }) => {
    const bridge = await installFakeBridge(page);
    await page.goto("/workspace/apps/ci-board");
    await expect(page.getByTestId("app-access-gate")).toBeVisible();
    await expect(page.locator('[data-testid="app-frame"]')).toHaveCount(0);
    const card = page.getByTestId("app-approval-card");
    await expect(card).toContainText(
      "Read open pull requests waiting on your review",
    );
    await expect(card).toContainText(
      "Data is shown in the app only; the assistant never sees it.",
    );
    await expect(page.getByTestId("app-card-hash")).toHaveAttribute(
      "title",
      HASH_PENDING,
    );
    // Nothing to tick, nothing pre-ticked: one button.
    await expect(
      card.locator('input[type="checkbox"], [role="checkbox"]'),
    ).toHaveCount(0);
    await expect(card.getByRole("button")).toHaveCount(1);
    expect(bridge.log.approvals).toEqual([]);
    await page.getByTestId("app-card-allow").click();
    await expect
      .poll(() => bridge.log.approvals)
      .toEqual([
        { manifest_hash: HASH_PENDING, card_id: expect.any(String) as unknown },
      ]);
    await expect(page.locator('[data-testid="app-frame"]')).toHaveCount(1);
  });

  test("a revoked app shows Approve again in place of tiles", async ({
    page,
  }) => {
    await installFakeBridge(page, { apps: [demoApp({ status: "revoked" })] });
    await page.goto("/workspace/apps/today");
    await expect(page.getByTestId("app-access-gate")).toContainText(
      "You revoked this app's access.",
    );
    await expect(page.getByTestId("app-approval-card")).toContainText(
      "Approve again",
    );
    await expect(page.locator('[data-testid="app-frame"]')).toHaveCount(0);
  });
});

test.describe("the library", () => {
  test("lists apps; pins one to the sidebar through the preferences API", async ({
    page,
  }) => {
    const bridge = await installFakeBridge(page);
    await page.goto("/workspace/apps");
    const rows = page.getByTestId("app-row");
    await expect(rows).toHaveCount(2);
    await expect(rows.nth(0)).toContainText("Today");
    await expect(rows.nth(0)).toContainText("v3");
    await expect(rows.nth(0)).toContainText("Approved");
    await expect(rows.nth(0)).toContainText("Last opened 12 min ago");
    await expect(rows.nth(1)).toContainText("Needs approval");
    await expect(rows.nth(1)).toContainText("Never opened");
    await rows.nth(0).getByTestId("app-pin").click();
    await expect.poll(() => bridge.log.pinWrites).toEqual([["today"]]);
    const pinned = page.locator(
      '[data-sidebar="sidebar"] [data-testid="pinned-app"]',
    );
    await expect(pinned).toHaveText("Today");
    await pinned.click();
    await expect(page).toHaveURL(/\/workspace\/apps\/today$/);
    await appFrame(page);
  });

  test("History: Restore writes a new version, naming the version it read", async ({
    page,
  }) => {
    const bridge = await installFakeBridge(page);
    await page.goto("/workspace/apps");
    const row = page.getByTestId("app-row").first();
    await row.getByTestId("app-history").click();
    const panel = row.getByTestId("app-history-panel");
    await expect(panel.locator("li")).toHaveCount(3);
    await expect(panel.locator("li").first()).toContainText("Current");
    await panel
      .locator('li[data-version="1"]')
      .getByTestId("app-restore")
      .click();
    await expect
      .poll(() => bridge.log.restores)
      .toEqual([{ to_version: 1, base_version: 3 }]);
    await expect(panel).toContainText("Restored version 1 as version 4.");
  });

  test("Permissions: each source in words, granted when; Revoke ends access", async ({
    page,
  }) => {
    const bridge = await installFakeBridge(page);
    await page.goto("/workspace/apps");
    const row = page.getByTestId("app-row").first();
    await row.getByTestId("app-permissions").click();
    const panel = row.getByTestId("app-permissions-panel");
    await expect(panel).toContainText("Approved Nov 12, 2026");
    await expect(panel).toContainText(
      "Read today's events from Google Calendar",
    );
    await expect(panel).toContainText("Updated 4 min ago");
    await panel.getByTestId("app-revoke").click();
    expect(bridge.log.revokes).toEqual([]);
    await panel.getByTestId("app-revoke-confirm").click();
    await expect.poll(() => bridge.log.revokes).toEqual(["today"]);
    await expect(row.getByTestId("app-row-status")).toHaveText(
      "Access revoked",
    );
  });

  test("a pending app's card in the library; a changed app refuses the stale press", async ({
    page,
  }) => {
    const bridge = await installFakeBridge(page, {
      apps: [demoApp(), pendingApp()],
    });
    await page.goto("/workspace/apps");
    const row = page.getByTestId("app-row").nth(1);
    await row.getByTestId("app-review").click();
    await expect(row.getByTestId("app-approval-card")).toBeVisible();
    // The app changes on the server after the card was drawn.
    bridge.apps.get("ci-board")!.hash = "f".repeat(64);
    await row.getByTestId("app-card-allow").click();
    await expect(row.getByRole("alert")).toContainText(
      "This app changed after this card was drawn",
    );
    await expect(row.getByTestId("app-row-status")).toHaveText(
      "Needs approval",
    );
  });

  test("the chat shows the App access card raised in it", async ({ page }) => {
    await installFakeBridge(page);
    const json = (body: unknown) => ({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(body),
    });
    await page.route("**/api/langgraph/**", (route) => {
      const url = route.request().url();
      if (url.includes("/history")) return route.fulfill(json([]));
      if (url.includes("/runs")) return route.fulfill(json([]));
      if (url.includes("/threads/search")) return route.fulfill(json([]));
      return route.fulfill(
        json({ thread_id: "t1", values: { messages: [] }, metadata: {} }),
      );
    });
    await page.route("**/api/confirmations", (route) =>
      route.fulfill(json({ actions: [], readable: true, error: "" })),
    );
    await page.goto("/workspace/chats/t1");
    await expect(page.getByTestId("thread-app-approvals")).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByTestId("app-approval-card")).toContainText(
      "CI board",
    );
  });
});

for (const scheme of ["light", "dark"] as const) {
  test.describe(`${scheme} theme`, () => {
    test.use({ colorScheme: scheme, viewport: { width: 1280, height: 800 } });

    test(`library, card and host meet AA (${scheme})`, async ({ page }) => {
      await setTheme(page, scheme);
      await installFakeBridge(page, { pins: ["today"] });
      await page.goto("/workspace/apps", { waitUntil: "networkidle" });
      expect(
        await page.evaluate(() =>
          document.documentElement.classList.contains("dark"),
        ),
      ).toBe(scheme === "dark");
      const row = page.getByTestId("app-row").nth(1);
      await row.getByTestId("app-review").click();
      await expect(row.getByTestId("app-approval-card")).toBeVisible();
      await contrast(page);
      await shot(page, `library-${scheme}`);
      await page
        .getByTestId("app-row")
        .first()
        .getByTestId("app-permissions")
        .click();
      await expect(page.getByTestId("app-permissions-panel")).toBeVisible();
      await contrast(page);
      await page.goto("/workspace/apps/today", { waitUntil: "networkidle" });
      const frame = await appFrame(page);
      await contrast(page);
      // The demo app's own text, measured inside the frame.
      const inFrame = await frame.evaluate(lowContrastText);
      expect(inFrame.map((f) => f.text)).toEqual([]);
      await shot(page, `host-${scheme}`);
      await page.goto("/workspace/apps/ci-board", { waitUntil: "networkidle" });
      await contrast(page);
      await shot(page, `approval-${scheme}`);
    });
  });
}

test.describe("phone width", () => {
  test.use({ viewport: { width: 360, height: 780 } });
  for (const scheme of ["light", "dark"] as const) {
    test(`library and host fit 360 px with no sideways scroll (${scheme})`, async ({
      page,
    }) => {
      await setTheme(page, scheme);
      await installFakeBridge(page);
      for (const path of [
        "/workspace/apps",
        "/workspace/apps/today",
        "/workspace/apps/ci-board",
      ]) {
        await page.goto(path, { waitUntil: "networkidle" });
        if (path === "/workspace/apps/today") await appFrame(page);
        const overflow = await page.evaluate(() => {
          const el =
            document.querySelector('[data-testid="workspace-scroll"]') ??
            document.documentElement;
          return el.scrollWidth - el.clientWidth;
        });
        expect(overflow, path).toBeLessThanOrEqual(0);
        await contrast(page);
        await shot(page, `phone-${scheme}-${path.split("/").pop()}`);
      }
    });
  }
});
