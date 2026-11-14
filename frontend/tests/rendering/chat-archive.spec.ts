import { expect, test, type Page } from "@playwright/test";

import { lowContrastText } from "./contrast-probe";

/**
 * Archive and folders for chats. Recent and Chats hide archived chats (the
 * gateway's search does, unless asked); Chats has an Archived view with
 * folders and Unarchive; a chat's menu has Archive and Move to Tests; an
 * archived chat still opens, with a banner. AA in both themes.
 *
 * NO BACKEND: the routes are intercepted; the gateway's filtering and
 * validation are pytest's (backend/tests/test_threads_archive.py).
 */

const json = (body: unknown) => ({
  status: 200,
  contentType: "application/json",
  body: JSON.stringify(body),
});

interface Row {
  thread_id: string;
  metadata: Record<string, unknown>;
  title: string;
}

async function serve(page: Page) {
  const rows: Row[] = [
    { thread_id: "live", metadata: {}, title: "Launch plan" },
    {
      thread_id: "t1",
      metadata: { archived: true, folder: "Tests" },
      title: "Test chat one",
    },
    { thread_id: "old", metadata: { archived: true }, title: "Old notes" },
  ];
  const patches: { id: string; body: unknown }[] = [];
  const now = new Date().toISOString();
  const view = (r: Row) => ({
    thread_id: r.thread_id,
    updated_at: now,
    created_at: now,
    metadata: r.metadata,
    values: { title: r.title },
  });
  await page.route("**/threads/search", (route) => {
    const body = (route.request().postDataJSON() ?? {}) as {
      archived?: boolean | "all";
    };
    const shown = rows.filter((r) => {
      const a = r.metadata.archived === true;
      return body.archived === "all" ? true : body.archived === true ? a : !a;
    });
    return route.fulfill(json(shown.map(view)));
  });
  await page.route(/\/api\/threads\/[^/]+$/, (route) => {
    const req = route.request();
    const id = decodeURIComponent(
      new URL(req.url()).pathname.split("/").pop()!,
    );
    const row = rows.find((r) => r.thread_id === id);
    if (!row) return route.fulfill({ status: 404, body: "{}" });
    if (req.method() === "PATCH") {
      const body = req.postDataJSON() as { metadata: Record<string, unknown> };
      patches.push({ id, body });
      Object.assign(row.metadata, body.metadata);
    }
    return route.fulfill(json(view(row)));
  });
  await page.route("**/api/langgraph/**", (route) => {
    const url = route.request().url();
    if (url.includes("/threads/search")) return route.fallback();
    if (url.includes("/history") || url.includes("/runs"))
      return route.fulfill(json([]));
    return route.fulfill(
      json({ thread_id: "t1", values: { messages: [] }, metadata: {} }),
    );
  });
  return { rows, patches };
}

test("Recent and Chats hide archived chats; the Archived view lists them by folder", async ({
  page,
}) => {
  await serve(page);
  await page.goto("/workspace/chats");
  const list = page.getByTestId("chats-list");
  await expect(list).toContainText("Launch plan");
  await expect(list).not.toContainText("Test chat one");
  const sidebar = page.locator('[data-sidebar="sidebar"]');
  await expect(sidebar).toContainText("Launch plan");
  await expect(sidebar).not.toContainText("Test chat one");
  await page.getByTestId("chats-view-archived").click();
  await expect(list).toContainText("Test chat one");
  await expect(list).toContainText("Old notes");
  await page.getByTestId("chats-folder").filter({ hasText: "Tests" }).click();
  await expect(list).toContainText("Test chat one");
  await expect(list).not.toContainText("Old notes");
});

test("Unarchive from the Archived view sends archived: false", async ({
  page,
}) => {
  const { patches } = await serve(page);
  await page.goto("/workspace/chats");
  await page.getByTestId("chats-view-archived").click();
  const row = page
    .getByTestId("chats-list")
    .locator("li", { hasText: "Old notes" });
  await row.getByTestId("chat-unarchive").click();
  await expect
    .poll(() => patches)
    .toEqual([{ id: "old", body: { metadata: { archived: false } } }]);
  await page.getByTestId("chats-view-active").click();
  await expect(page.getByTestId("chats-list")).toContainText("Old notes");
});

test("a chat's menu archives it, or moves it to Tests", async ({ page }) => {
  const { patches } = await serve(page);
  await page.goto("/workspace/chats");
  const item = page.locator(
    '[data-sidebar="sidebar"] [data-sidebar="menu-item"]',
    { hasText: "Launch plan" },
  );
  await item.hover();
  await item.locator('[data-sidebar="menu-action"], button').last().click();
  await page.getByTestId("chat-move-tests").click();
  await expect
    .poll(() => patches)
    .toEqual([
      { id: "live", body: { metadata: { archived: true, folder: "Tests" } } },
    ]);
  await expect(page.locator('[data-sidebar="sidebar"]')).not.toContainText(
    "Launch plan",
  );
});

test("an archived chat still opens, with a banner and Unarchive", async ({
  page,
}) => {
  const { patches } = await serve(page);
  await page.goto("/workspace/chats/t1");
  const banner = page.getByTestId("archived-banner");
  await expect(banner).toContainText("Archived · Tests");
  await page.getByTestId("archived-banner-unarchive").click();
  await expect
    .poll(() => patches)
    .toEqual([{ id: "t1", body: { metadata: { archived: false } } }]);
  await expect(banner).toHaveCount(0);
});

for (const scheme of ["light", "dark"] as const) {
  for (const width of [1280, 390]) {
    test(`Archived view and banner meet AA (${scheme}, ${width} px)`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: 800 });
      await page.emulateMedia({ colorScheme: scheme });
      await page.addInitScript((t) => {
        try {
          localStorage.setItem("theme", t);
        } catch {}
      }, scheme);
      await serve(page);
      await page.goto("/workspace/chats", { waitUntil: "networkidle" });
      await page.getByTestId("chats-view-archived").click();
      await expect(page.getByTestId("chats-list")).toContainText(
        "Test chat one",
      );
      const report = (found: Awaited<ReturnType<typeof lowContrastText>>) =>
        found
          .map((f) => `${f.ratio}/${f.need} "${f.text}" ${f.color} [${f.cls}]`)
          .join("\n");
      let found = await page.evaluate(lowContrastText);
      expect(found, report(found)).toEqual([]);
      const overflow = await page.evaluate(() => {
        const el =
          document.querySelector('[data-testid="workspace-scroll"]') ??
          document.documentElement;
        return el.scrollWidth - el.clientWidth;
      });
      expect(overflow).toBeLessThanOrEqual(0);
      await page.goto("/workspace/chats/t1", { waitUntil: "networkidle" });
      await expect(page.getByTestId("archived-banner")).toBeVisible();
      found = await page.evaluate(lowContrastText);
      expect(found, report(found)).toEqual([]);
    });
  }
}
