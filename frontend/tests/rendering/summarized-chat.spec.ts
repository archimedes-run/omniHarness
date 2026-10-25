import { mkdirSync, readFileSync } from "fs";
import { fileURLToPath } from "node:url";

import { expect, test, type Page, type Route } from "@playwright/test";

import { lowContrastText } from "./contrast-probe";

/**
 * A long research chat after its context was summarized (dogfooding,
 * 2026-10-24). The backend folds the conversation into ONE summary message
 * (a human message named "summary": the model's context) plus the latest few.
 *
 * - The summary ("## SESSION INTENT …") is never shown: not streamed, not
 *   after a reload.
 * - The person keeps seeing what they said and were shown: while streaming
 *   (the summarized messages move into the display history) and after a
 *   reload (the history is read back from the run journal, every page).
 *
 * The thread, the stream and the journal are RECORDED FROM THE REAL BACKEND
 * (fixtures/summarized-research.json; see its `_about`). Only the transport
 * is intercepted. The journal is served in pages of 4 rows, as a long run's
 * is (the route returns the newest page first).
 */
const FIX = JSON.parse(
  readFileSync(
    fileURLToPath(
      new URL("./fixtures/summarized-research.json", import.meta.url),
    ),
    "utf8",
  ),
) as {
  state1: unknown;
  runs1: unknown[];
  journal1: Record<string, Row[]>;
  run2_sse: string;
  state2: unknown;
  runs2: unknown[];
  journal2: Record<string, Row[]>;
  leaked_summary_chunks: string[];
};
type Row = { seq: number; metadata: { caller?: string } };

const THREAD = "00000000-0000-0000-0000-000000000001";
const FIRST = "find 5 great date-night restaurants in Philly with links";
const SECOND = "now find 3 brunch spots too";
const FIRST_ANSWER = "Run one answer: Vetri Cucina";
const SECOND_ANSWER = "Brunch picks: Talula's Garden";
const PAGE_ROWS = 4;
// Review screenshots are saved only when a folder is named.
const SHOTS = process.env.SUMMARY_SHOTS_DIR;

const json = (body: unknown) => ({
  status: 200,
  contentType: "application/json",
  body: JSON.stringify(body),
});

/** The run's journal, newest page first, as the backend's route pages it. */
function journalPage(rows: Row[], url: URL) {
  const before = url.searchParams.get("before_seq");
  const older = before === null ? rows : rows.filter((r) => r.seq < +before);
  const data = older.slice(-PAGE_ROWS);
  return { data, has_more: older.length > data.length };
}

type Stage = {
  state: unknown;
  runs: unknown[];
  journal: Record<string, Row[]>;
};

async function mockThread(
  page: Page,
  scheme: "light" | "dark",
  stage: { current: Stage },
  stream?: { body: string; after?: Stage; holdState?: boolean },
) {
  await page.addInitScript((t) => {
    try {
      localStorage.setItem("theme", t);
    } catch {}
  }, scheme);
  let streamed = false;
  await page.route("**/api/langgraph/**", (route: Route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/runs/stream") && stream) {
      streamed = true;
      if (stream.after) stage.current = stream.after;
      return route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: stream.body,
      });
    }
    if (url.pathname.endsWith("/history")) {
      // An older server's stream, cut while the summary streams: the state
      // fetched after it never answers, so the streamed messages stay up.
      if (streamed && stream?.holdState) return;
      return route.fulfill(json([stage.current.state]));
    }
    if (url.pathname.endsWith("/threads/search"))
      return route.fulfill(json([]));
    if (url.pathname.endsWith("/runs"))
      return route.fulfill(json(stage.current.runs));
    return route.fulfill(json(stage.current.state));
  });
  await page.route(/\/api\/threads\/[^/]+\/runs\/[^/]+\/messages/, (route) => {
    const url = new URL(route.request().url());
    const runId = url.pathname.split("/").at(-2)!;
    return route.fulfill(
      json(journalPage(stage.current.journal[runId] ?? [], url)),
    );
  });
  await page.route("**/api/confirmations", (route) =>
    route.fulfill(json({ actions: [], readable: true, error: "" })),
  );
  await page.route("**/api/inbox/alerts", (route) =>
    route.fulfill(json({ alerts: [], waiting_count: 0 })),
  );
  await page.route("**/api/threads/*/suggestions", (route) =>
    route.fulfill(json({ suggestions: [] })),
  );
}

/** Scroll the thread to its top until `text` shows (older pages load there). */
async function scrollUntilVisible(page: Page, text: string) {
  for (let i = 0; i < 30; i++) {
    if (await page.getByText(text, { exact: true }).isVisible()) return;
    await page.evaluate(() => {
      for (const node of document.querySelectorAll("*")) {
        if (
          node.scrollHeight > node.clientHeight + 10 &&
          getComputedStyle(node).overflowY !== "visible"
        ) {
          node.scrollTo({ top: 0 });
        }
      }
    });
    await page.waitForTimeout(700);
  }
  await expect(page.getByText(text, { exact: true })).toBeVisible();
}

async function expectNoSummary(page: Page) {
  await expect(page.getByText(/SESSION INTENT/)).toHaveCount(0);
  await expect(
    page.getByText(/Here is a summary of the conversation/),
  ).toHaveCount(0);
  await expect(page.getByText(/NEXT STEPS/)).toHaveCount(0);
}

async function send(page: Page, text: string) {
  const box = page.getByLabel("Message", { exact: true });
  await expect(box).toBeVisible({ timeout: 15_000 });
  await box.fill(text);
  await box.press("Enter");
}

const STAGE1: Stage = {
  state: FIX.state1,
  runs: FIX.runs1,
  journal: FIX.journal1,
};
const STAGE2: Stage = {
  state: FIX.state2,
  runs: FIX.runs2,
  journal: FIX.journal2,
};

for (const scheme of ["light", "dark"] as const) {
  test.describe(`${scheme} theme`, () => {
    test.use({ colorScheme: scheme, viewport: { width: 1440, height: 2000 } });

    test("after a reload, every message from the person shows and the summary never does", async ({
      page,
    }) => {
      await mockThread(page, scheme, { current: STAGE2 });
      await page.goto(`/workspace/chats/${THREAD}`, {
        waitUntil: "networkidle",
      });
      await expect(
        page.getByText(SECOND_ANSWER, { exact: false }),
      ).toBeVisible();
      await expect(page.getByText(SECOND, { exact: true })).toBeVisible();
      await scrollUntilVisible(page, FIRST);
      await expect(
        page.getByText(FIRST_ANSWER, { exact: false }),
      ).toBeVisible();
      await expectNoSummary(page);
      // In order: the first turn, then the second.
      const first = await page.getByText(FIRST, { exact: true }).boundingBox();
      const second = await page
        .getByText(SECOND, { exact: true })
        .boundingBox();
      expect(first!.y).toBeLessThan(second!.y);
      if (SHOTS) {
        mkdirSync(SHOTS, { recursive: true });
        await page.screenshot({
          path: `${SHOTS}/summarized-chat-reload-${scheme}.png`,
          fullPage: true,
        });
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

test.describe("while the turn streams", () => {
  test.use({ viewport: { width: 1440, height: 2000 } });

  test("a turn that summarizes keeps the person's messages on screen", async ({
    page,
  }) => {
    const stage = { current: STAGE1 };
    await mockThread(page, "light", stage, {
      body: FIX.run2_sse,
      after: STAGE2,
    });
    await page.goto(`/workspace/chats/${THREAD}`, { waitUntil: "networkidle" });
    await expect(page.getByText(FIRST_ANSWER, { exact: false })).toBeVisible();
    await scrollUntilVisible(page, FIRST);

    await send(page, SECOND);
    await expect(page.getByText(SECOND_ANSWER, { exact: false })).toBeVisible();
    // The live thread is now [summary, the last few]; the rest moved to the
    // display history, so the whole conversation is still on screen.
    await expect(page.getByText(SECOND, { exact: true })).toBeVisible();
    await expect(page.getByText(FIRST, { exact: true })).toBeVisible();
    await expect(page.getByText(FIRST_ANSWER, { exact: false })).toBeVisible();
    await expect(page.getByText(SECOND, { exact: true })).toHaveCount(1);
    await expect(page.getByText(FIRST, { exact: true })).toHaveCount(1);
    // Every step of both turns is still there: each turn's group reads
    // "3 more steps" above its last step, as after a reload.
    await expect(page.getByText("3 more steps", { exact: true })).toHaveCount(
      2,
    );
    await expectNoSummary(page);
    if (SHOTS) {
      mkdirSync(SHOTS, { recursive: true });
      await page.waitForTimeout(1000); // the reply's fade-in
      await page.screenshot({
        path: `${SHOTS}/summarized-chat-streamed-light.png`,
        fullPage: true,
      });
    }
  });

  test("a summarizer reply streamed by an older server is never shown", async ({
    page,
  }) => {
    // The recorded stream up to where the summary replaces the context, then
    // the summarizer's own chunks exactly as the backend streamed them
    // before it tagged that call "nostream"; the stream ends there.
    const events = FIX.run2_sse.split("\n\n");
    const cut = events.findIndex((e) => e.includes('"__remove_all__"'));
    expect(cut).toBeGreaterThan(0);
    const body = [
      ...events.slice(0, cut),
      ...FIX.leaked_summary_chunks,
      "",
    ].join("\n\n");
    const stage = { current: STAGE1 };
    await mockThread(page, "light", stage, { body, holdState: true });
    await page.goto(`/workspace/chats/${THREAD}`, { waitUntil: "networkidle" });
    await expect(page.getByText(FIRST_ANSWER, { exact: false })).toBeVisible();

    const done = page.waitForResponse((r) => r.url().endsWith("/runs/stream"));
    await send(page, SECOND);
    await done;
    await expect(page.getByText(SECOND, { exact: true })).toBeVisible();
    // Give the stream's last events time to render.
    await page.waitForTimeout(1500);
    await expectNoSummary(page);
  });
});
