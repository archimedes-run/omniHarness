import { mkdirSync } from "fs";

import { expect, test, type Page } from "@playwright/test";

import { lowContrastText } from "./contrast-probe";

/**
 * A bare URL in the agent's answer reads as its real URL (dogfooding,
 * 2026-10-24): "https://vetricucina.example/landing/", not
 * "hxxps://vetricucina[.]example/landing/". It is the same outside-link
 * button as a markdown link in the same answer (core/streamdown/
 * content-url-guard.ts): nothing is fetched on render, and it opens (no
 * opener, no referrer) only once the person confirms. A "link" to any other
 * scheme is inert text.
 *
 * NO BACKEND: the thread's state is intercepted.
 */
const THREAD = "44444444-5555-6666-7777-888888888888";
const BARE = "https://vetricucina.example/landing/";
const WWW = "www.zahavrestaurant.example";
const ANSWER = [
  `Book Vetri at ${BARE} or call Zahav (${WWW}).`,
  "",
  "Sources:",
  "- [Vetri Cucina menu](https://vetricucina.example/menu)",
  "",
  "Not links: javascript:alert(1), [run me](javascript:alert(2)) and [a page](data:text/html,hi).",
  "",
  "Lookalikes: [https://good.example/login](https://evil.example/x), https://good.example@evil.example/y and https://evil.example/\u202egpj.exe.",
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
    const opened: unknown[] = [];
    (window as unknown as { __opened: unknown[] }).__opened = opened;
    window.open = (...args: unknown[]) => {
      opened.push(args);
      return null;
    };
  }, scheme);
  const state = {
    values: {
      title: "Date night",
      messages: [
        { type: "human", id: "h1", content: "find date-night restaurants" },
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

    test("a bare URL in the answer reads as its real URL, opens only on confirm, and nothing is fetched", async ({
      page,
    }) => {
      const outside: string[] = [];
      page.on("request", (r) => {
        if (new URL(r.url()).hostname.endsWith(".example"))
          outside.push(r.url());
      });
      await open(page, scheme);

      const bare = page.getByRole("button", { name: BARE, exact: true });
      await expect(bare).toBeVisible();
      await expect(bare).toHaveAttribute("data-external-link", "");
      const www = page.getByRole("button", { name: WWW, exact: true });
      await expect(www).toBeVisible();
      // The markdown link in the same answer is the same kind of button.
      await expect(
        page.getByRole("button", { name: "Vetri Cucina menu", exact: true }),
      ).toHaveAttribute("data-external-link", "");
      const answer = page.getByText(/Book Vetri at/);
      await expect(answer).not.toContainText("hxxp");
      await expect(answer).not.toContainText("[.]");

      // Other schemes are text: no button, no href.
      await expect(
        page.getByText(/Not links: javascript:alert\(1\)/),
      ).toBeVisible();
      await expect(page.locator("[data-inert-link]")).toHaveCount(2);
      await expect(
        page.getByRole("button", { name: "run me", exact: true }),
      ).toHaveCount(0);
      await expect(
        page.locator('[href^="javascript:" i], [href^="data:" i]'),
      ).toHaveCount(0);

      // A label never names another host than the link opens, and carries
      // no invisible characters.
      for (const real of [
        "https://evil.example/x",
        "https://evil.example/y",
        "https://evil.example/gpj.exe",
      ]) {
        await expect(
          page.getByRole("button", { name: real, exact: true }),
        ).toBeVisible();
      }
      const lookalikes = page.getByText(/^Lookalikes:/);
      await expect(lookalikes).not.toContainText("good.example");
      expect(await lookalikes.textContent()).not.toContain("\u202e");

      // Opening it: the full URL first, then a new window with no opener and
      // no referrer, only after the person says so.
      await bare.click();
      const dialog = page.getByRole("dialog");
      await expect(dialog).toContainText(BARE);
      if (SHOTS) {
        mkdirSync(SHOTS, { recursive: true });
        await page.screenshot({
          path: `${SHOTS}/agent-links-dialog-${scheme}.png`,
        });
      }
      await dialog.getByRole("button", { name: "Open link" }).click();
      expect(
        await page.evaluate(
          () => (window as unknown as { __opened: unknown[] }).__opened,
        ),
      ).toEqual([[BARE, "_blank", "noopener,noreferrer"]]);
      expect(outside, "a request reached an outside host").toEqual([]);
    });

    test("an answer with links meets WCAG AA", async ({ page }) => {
      await open(page, scheme);
      await expect(
        page.getByRole("button", { name: BARE, exact: true }),
      ).toBeVisible();
      if (SHOTS) {
        mkdirSync(SHOTS, { recursive: true });
        await page.screenshot({ path: `${SHOTS}/agent-links-${scheme}.png` });
      }
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
