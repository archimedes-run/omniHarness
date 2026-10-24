import { mkdirSync } from "fs";

import { expect, test, type Page } from "@playwright/test";

import { EIGHT_PLUS, json, message, stub, THREAD } from "./chat-bar-stubs";

/**
 * The chat bar never covers the thread (a lead -> repo-analyst chat whose
 * answer ends with suggested follow-ups):
 *
 * 1. the suggested follow-ups sit under the last message, in the thread's
 *    flow: they never overlap a message;
 * 2. the thread's clear space at the bottom follows the bar's real height,
 *    with its chips on two lines and its textarea grown: scrolled to the
 *    bottom, the last message ends above the bar.
 *
 * NO BACKEND: the thread, its run and the suggestions are intercepted.
 */
const SHOTS = process.env.CHAT_SHOTS_DIR;
const PARAGRAPH =
  "The repository ships a self-hosted agent workspace: a Next.js frontend, a gateway and a LangGraph runtime, with a policy layer between every tool call and the outside world.";

const history = [
  { type: "human", id: "h1", content: "What is going on with this repo?" },
  {
    type: "ai",
    id: "a1",
    content: Array.from({ length: 6 }, () => PARAGRAPH).join("\n\n"),
  },
];
const LAST_LINE = "Want me to expand any of these sections?";
const answer = {
  type: "ai",
  id: "a2",
  content: [
    ...Array.from({ length: 5 }, (_, i) => `${i + 1}. ${PARAGRAPH}`),
    "",
    LAST_LINE,
  ].join("\n"),
};
const SUGGESTIONS = [
  "Expand with a dependency and CVE matrix and a merge readiness checklist",
  "Draft a hardening sprint issue board that groups the LOW and MEDIUM follow-ups",
  "Generate an architecture overview with Mermaid diagrams for new contributors",
];

async function open(page: Page) {
  await stub(page, EIGHT_PLUS);
  const state = (messages: unknown[]) => ({
    values: { title: "Repository analysis", messages },
    next: [],
    tasks: [],
    metadata: {},
    created_at: new Date().toISOString(),
    checkpoint: { thread_id: THREAD, checkpoint_id: "c1", checkpoint_ns: "" },
    parent_checkpoint: null,
  });
  // What the thread holds: its history, then the run's messages once it ran.
  let saved: unknown[] = history;
  // Registered after stub(): Playwright tries the newest route first.
  await page.route("**/api/langgraph/**", (route) => {
    const url = route.request().url();
    if (url.includes("/runs/stream")) {
      const ask = { type: "human", id: "h2", content: "Summarise it" };
      saved = [...history, ask, answer];
      const events = [
        { event: "metadata", data: { run_id: "r1", thread_id: THREAD } },
        {
          event: "values",
          data: {
            title: "Repository analysis",
            messages: [...history, ask, answer],
          },
        },
        { event: "end", data: {} },
      ];
      return route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: events
          .map((e) => `event: ${e.event}\ndata: ${JSON.stringify(e.data)}\n\n`)
          .join(""),
      });
    }
    if (url.includes("/history")) return json(route, [state(saved)]);
    if (url.includes("/runs") || url.includes("/search"))
      return json(route, []);
    return json(route, state(saved));
  });
  await page.route("**/api/confirmations", (route) =>
    json(route, { actions: [], readable: true, error: "" }),
  );
  await page.route("**/api/inbox/alerts", (route) =>
    json(route, { alerts: [], waiting_count: 0 }),
  );
  await page.route("**/api/threads/*/suggestions", (route) =>
    json(route, { suggestions: SUGGESTIONS }),
  );
  await page.goto(`/workspace/chats/${THREAD}`, { waitUntil: "networkidle" });
  await expect(
    page.getByText("What is going on with this repo?"),
  ).toBeVisible();
  await message(page).fill("Summarise it");
  await message(page).press("Enter");
  await expect(page.getByText(LAST_LINE)).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole("button", { name: SUGGESTIONS[0] })).toBeVisible({
    timeout: 15_000,
  });
}

type Box = { x: number; y: number; width: number; height: number };
const overlaps = (a: Box, b: Box) =>
  a.x < b.x + b.width &&
  b.x < a.x + a.width &&
  a.y < b.y + b.height &&
  b.y < a.y + a.height;

/** Scroll the thread to its very bottom and let it settle. */
async function scrollToBottom(page: Page) {
  await page.getByTestId("message-list-spacer").evaluate((spacer) => {
    let el: HTMLElement | null = spacer.parentElement;
    while (el && !(el.scrollHeight > el.clientHeight + 1)) {
      el = el.parentElement;
    }
    el?.scrollTo({ top: el.scrollHeight });
  });
  await page.waitForTimeout(400);
}

/** Scroll the thread by `dy` px (negative: up). */
async function scrollBy(page: Page, dy: number) {
  await page.getByTestId("message-list-spacer").evaluate((spacer, by) => {
    let el: HTMLElement | null = spacer.parentElement;
    while (el && !(el.scrollHeight > el.clientHeight + 1)) {
      el = el.parentElement;
    }
    el?.scrollBy({ top: by });
  }, dy);
  await page.waitForTimeout(400);
}

/** Every message box in the thread: the conversation's children, minus the
 * follow-ups slot and the bottom spacer. */
async function messageBoxes(page: Page): Promise<Box[]> {
  return page.getByTestId("message-list-spacer").evaluate((spacer) =>
    [...spacer.parentElement!.children]
      .filter(
        (el) =>
          el !== spacer &&
          el.getAttribute("data-testid") !== "followups-slot" &&
          el.getBoundingClientRect().height > 0,
      )
      .map((el) => {
        const r = el.getBoundingClientRect();
        return { x: r.x, y: r.y, width: r.width, height: r.height };
      }),
  );
}

for (const scheme of ["light", "dark"] as const) {
  test.describe(`${scheme} theme`, () => {
    test.use({ colorScheme: scheme, viewport: { width: 1440, height: 900 } });

    test.beforeEach(async ({ page }) => {
      await page.addInitScript((t) => {
        try {
          localStorage.setItem("theme", t);
        } catch {}
      }, scheme);
    });

    test("the follow-ups sit under the last message and never overlap one", async ({
      page,
    }) => {
      await open(page);
      await scrollToBottom(page);
      const chips = page.getByTestId("followups");
      await expect(chips).toBeVisible();
      const chipsBox = (await chips.boundingBox())!;
      const boxes = await messageBoxes(page);
      expect(boxes.length).toBeGreaterThan(2);
      for (const box of boxes) {
        expect(
          overlaps(chipsBox, box),
          `follow-ups ${JSON.stringify(chipsBox)} overlap a message ${JSON.stringify(box)}`,
        ).toBe(false);
      }
      // Under the last message, and above the bar.
      const last = (await page.getByText(LAST_LINE).boundingBox())!;
      expect(chipsBox.y).toBeGreaterThanOrEqual(last.y + last.height);
      const bar = (await page.getByTestId("chat-bar").boundingBox())!;
      expect(chipsBox.y + chipsBox.height).toBeLessThanOrEqual(bar.y);

      // In the flow: scrolled back up, they move with the thread instead of
      // floating over the message text (what the live chat showed).
      await scrollBy(page, -300);
      const moved = (await chips.boundingBox())!;
      for (const box of await messageBoxes(page)) {
        expect(
          overlaps(moved, box),
          `scrolled up, follow-ups ${JSON.stringify(moved)} overlap a message ${JSON.stringify(box)}`,
        ).toBe(false);
      }
      expect(moved.y - chipsBox.y).toBeGreaterThan(250);
    });

    test("scrolled to the bottom, the last message ends above the bar, chips wrapped and textarea grown", async ({
      page,
    }) => {
      await open(page);
      // The bar's chips are on two lines, as in the live chat.
      const chipsRow = (await page.getByTestId("context-chips").boundingBox())!;
      expect(chipsRow.height).toBeGreaterThan(48);
      const before = (await page.getByTestId("chat-bar").boundingBox())!;
      await message(page).fill(
        Array.from({ length: 7 }, (_, i) => `line ${i + 1}`).join("\n"),
      );
      await expect
        .poll(
          async () =>
            (await page.getByTestId("chat-bar").boundingBox())!.height,
        )
        .toBeGreaterThan(before.height + 60);

      await scrollToBottom(page);
      const bar = (await page.getByTestId("chat-bar").boundingBox())!;
      const last = (await page.getByText(LAST_LINE).boundingBox())!;
      expect(
        last.y + last.height,
        `last message bottom ${last.y + last.height} > bar top ${bar.y}`,
      ).toBeLessThanOrEqual(bar.y);
      const chips = (await page.getByTestId("followups").boundingBox())!;
      expect(chips.y + chips.height).toBeLessThanOrEqual(bar.y);

      if (SHOTS) {
        mkdirSync(SHOTS, { recursive: true });
        // Past the chips' staggered fade-in.
        await page.waitForTimeout(1200);
        await page.screenshot({
          path: `${SHOTS}/chat-followups-${scheme}.png`,
        });
      }
    });
  });
}
