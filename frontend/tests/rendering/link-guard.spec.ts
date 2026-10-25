import { mkdirSync } from "fs";

import { expect, test, type Page } from "@playwright/test";

import { lowContrastText } from "./contrast-probe";

/**
 * Tighter same-origin and label checks for links and images in agent text.
 * This page is served over plain http, where the browser resolves
 * "https:host/p" to https://host/p: such a link or image must be neither live
 * nor fetched. Labels name the host the link really opens.
 *
 * NO BACKEND: the thread's state is intercepted.
 */
const THREAD = "55555555-6666-7777-8888-999999999999";
const ANSWER = [
  "Scheme-only: [menu](https:evil.example/p) and <https:evil.example/q>.",
  "",
  "![status](https:evil.example/pixel.png)",
  "",
  "Labels: [good​.example](https://evil.example/a), [gооgle.com](https://evil.example/b), [citation:good.example](https://evil.example/c).",
].join("\n");
const SHOTS = process.env.SUMMARY_SHOTS_DIR;

async function open(page: Page, scheme: "light" | "dark") {
  const json = (body: unknown) => ({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
  await page.addInitScript((t) => {
    try {
      localStorage.setItem("theme", t);
    } catch {}
  }, scheme);
  const state = {
    values: {
      title: "Links",
      messages: [
        { type: "human", id: "h1", content: "show me the links" },
        { type: "ai", id: "a1", content: ANSWER },
      ],
    },
    next: [],
    tasks: [],
    metadata: {},
    created_at: new Date().toISOString(),
    checkpoint: { thread_id: THREAD, checkpoint_id: "c1", checkpoint_ns: "" },
    parent_checkpoint: null,
  };
  await page.route("**/api/langgraph/**", (route) => {
    const url = route.request().url();
    if (url.includes("/history")) return route.fulfill(json([state]));
    if (url.includes("/runs") || url.includes("/search"))
      return route.fulfill(json([]));
    return route.fulfill(json(state));
  });
  await page.route("**/api/confirmations", (route) =>
    route.fulfill(json({ actions: [], readable: true, error: "" })),
  );
  await page.route("**/api/inbox/alerts", (route) =>
    route.fulfill(json({ alerts: [], waiting_count: 0 })),
  );
  await page.goto(`/workspace/chats/${THREAD}`, { waitUntil: "networkidle" });
}

for (const scheme of ["light", "dark"] as const) {
  test.describe(`${scheme} theme`, () => {
    test.use({ colorScheme: scheme, viewport: { width: 1440, height: 1200 } });

    test("a scheme-only link or image is neither live nor fetched, and labels name the real host", async ({
      page,
    }) => {
      const outside: string[] = [];
      page.on("request", (r) => {
        if (new URL(r.url()).hostname.endsWith(".example"))
          outside.push(r.url());
      });
      await open(page, scheme);
      await expect(page.getByText(/^Scheme-only:/)).toBeVisible();
      await expect(page.locator('a[href*="evil.example"]')).toHaveCount(0);
      await expect(page.locator('img[src*="evil.example"]')).toHaveCount(0);
      await expect(
        page.locator('link[rel="preload"][href*="evil"]'),
      ).toHaveCount(0);
      await expect(
        page.getByText("Image from evil[.]example not loaded"),
      ).toBeVisible();
      await expect(
        page.getByRole("button", {
          name: "https://evil.example/q",
          exact: true,
        }),
      ).toBeVisible();
      for (const real of ["https://evil.example/a", "https://evil.example/b"]) {
        await expect(
          page.getByRole("button", { name: real, exact: true }),
        ).toBeVisible();
      }
      const labels = page.getByText(/^Labels:/);
      await expect(labels).not.toContainText("good.example");
      await expect(labels).not.toContainText("gооgle");
      await expect(labels).toContainText("evil[.]example");
      if (SHOTS) {
        mkdirSync(SHOTS, { recursive: true });
        await page.screenshot({ path: `${SHOTS}/link-guard-${scheme}.png` });
      }
      expect(outside, "a request reached an outside host").toEqual([]);
      const found = await page.evaluate(lowContrastText);
      expect(
        found,
        found
          .map((f) => `${f.ratio}/${f.need} "${f.text}" ${f.color} [${f.cls}]`)
          .join("\n"),
      ).toEqual([]);
    });
  });
}
