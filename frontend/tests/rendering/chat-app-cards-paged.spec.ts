import { expect, test, type Page } from "@playwright/test";

import { EIGHT_PLUS, json, stub, THREAD } from "./chat-bar-stubs";

/**
 * App cards in a long chat that opens with "Load more" (only the newest run
 * is loaded), like the live Today build thread:
 *
 * - a decided card whose turn is not loaded is not shown at the end; after
 *   "Load more" it appears in place;
 * - an undecided card is always visible: while its turn is not loaded, once
 *   at the end, labelled "From earlier in this chat"; then in place.
 *
 * NO BACKEND: the runs, their journals and the cards are intercepted.
 */

const MARK = { omniharness_user_turn: true };
const PARAGRAPH =
  "Here is a long answer about the layout of the page, the tiles and the data they show, so that the newest run fills more than a screen and the older runs stay behind Load more until asked for.";

const human = (id: string, text: string) => ({
  type: "human",
  id,
  content: text,
  additional_kwargs: MARK,
});
const jobTurn = (n: number, report: string) => [
  {
    type: "ai",
    id: `a${n}`,
    content: "",
    tool_calls: [{ name: "code_job", args: {}, id: `cj${n}` }],
  },
  {
    type: "tool",
    id: `t${n}`,
    name: "code_job",
    tool_call_id: `cj${n}`,
    content: report,
  },
  { type: "ai", id: `d${n}`, content: `Turn ${n} done.` },
];

const RUN_MESSAGES: Record<string, unknown[]> = {
  run1: [
    human("h1", "build me a Today page"),
    ...jobTurn(
      1,
      "- App registered by the system: id today, version 1; it needs approval",
    ),
  ],
  run2: [
    human("h2", "add my pull requests"),
    ...jobTurn(
      2,
      "- App registered by the system: id today, version 2; offered",
    ),
  ],
  run3: [
    human("h3", "make it denser"),
    ...jobTurn(
      3,
      "- App registered by the system: id today, version 3 (card c3); offered",
    ),
  ],
  run4: [
    human("h4", "thanks, tell me about the layout"),
    {
      type: "ai",
      id: "d4",
      content: Array.from({ length: 10 }, () => PARAGRAPH).join("\n\n"),
    },
  ],
  run5: [
    human("h5", "and the colours?"),
    {
      type: "ai",
      id: "d5",
      content: Array.from({ length: 10 }, () => PARAGRAPH).join("\n\n"),
    },
  ],
};
const RUN_IDS = ["run1", "run2", "run3", "run4", "run5"];

const base = {
  app_id: "today",
  app_name: "Today",
  manifest_hash: "a".repeat(64),
  sources: [],
  sentence: "Data is shown in the app only; the assistant never sees it.",
  suggestion: false,
  suggestion_source: null,
  suggestion_words: null,
  thread_id: THREAD,
  checks_passed: true,
};
const CARDS = [
  {
    ...base,
    id: "c3",
    version: 3,
    kind: "version",
    status: "pending",
    keeps_version: 2,
    description: "Denser.",
    created_at: "2026-11-14T00:03:00Z",
    resolved_at: null,
  },
  {
    ...base,
    id: "c2",
    version: 2,
    kind: "version",
    status: "approved",
    keeps_version: 1,
    description: "Pull requests.",
    created_at: "2026-11-14T00:02:00Z",
    resolved_at: "2026-11-14T00:02:30Z",
  },
  {
    ...base,
    id: "c1",
    version: 1,
    kind: "access",
    status: "approved",
    keeps_version: null,
    created_at: "2026-11-14T00:01:00Z",
    resolved_at: "2026-11-14T00:01:30Z",
  },
];

async function open(page: Page) {
  await stub(page, EIGHT_PLUS);
  const now = new Date().toISOString();
  const state = {
    values: { title: "Today app", messages: RUN_MESSAGES.run5 },
    next: [],
    tasks: [],
    metadata: {},
    created_at: now,
    checkpoint: { thread_id: THREAD, checkpoint_id: "c1", checkpoint_ns: "" },
    parent_checkpoint: null,
  };
  const runs = RUN_IDS.map((run_id, i) => ({
    run_id,
    thread_id: THREAD,
    assistant_id: "lead_agent",
    status: "success",
    metadata: {},
    created_at: `2026-11-14T00:0${i}:00Z`,
    updated_at: `2026-11-14T00:0${i}:30Z`,
  }));
  await page.route("**/api/langgraph/**", (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/history")) return json(route, [state]);
    if (url.pathname.endsWith("/threads/search")) return json(route, []);
    if (url.pathname.endsWith("/runs")) return json(route, runs);
    return json(route, state);
  });
  await page.route(/\/api\/threads\/[^/]+\/runs\/[^/]+\/messages/, (route) => {
    const runId = new URL(route.request().url()).pathname.split("/").at(-2)!;
    const data = (RUN_MESSAGES[runId] ?? []).map((content, i) => ({
      thread_id: THREAD,
      run_id: runId,
      content,
      metadata: { caller: "lead_agent" },
      seq: i + 1,
      created_at: now,
    }));
    return json(route, { data, has_more: false });
  });
  await page.route("**/api/confirmations", (route) =>
    json(route, { actions: [], readable: true, error: "" }),
  );
  await page.route("**/api/apps/approvals*", (route) =>
    json(route, { cards: CARDS }),
  );
  await page.route(/\/api\/apps(\?|$)/, (route) =>
    json(route, {
      apps: [
        {
          id: "today",
          name: "Today",
          description: "",
          current_version: 2,
          manifest_hash: "a".repeat(64),
          status: "approved",
          pinned: false,
          updated_at: now,
          last_opened_at: null,
          pending_version: 3,
        },
      ],
    }),
  );
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto(`/workspace/chats/${THREAD}`, { waitUntil: "networkidle" });
  await expect(page.getByText("and the colours?")).toBeVisible();
}

test("decided cards wait for their turn; the undecided one shows at the end, labelled", async ({
  page,
}) => {
  await open(page);
  // Older runs are behind Load more (the turn of version 3 among them).
  await expect(page.getByText("build me a Today page")).toHaveCount(0);
  await expect(page.getByText("make it denser")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Load more" })).toBeVisible();
  // No decided card at the end.
  await expect(page.locator('[data-card-id="c1"]')).toHaveCount(0);
  await expect(page.locator('[data-card-id="c2"]')).toHaveCount(0);
  // The undecided card: visible once, at the end, labelled.
  const pending = page.locator(
    '[data-testid="app-approval-card"][data-card-id="c3"]',
  );
  await expect(pending).toHaveCount(1);
  await expect(page.getByTestId("app-card-earlier")).toHaveText(
    "From earlier in this chat",
  );
  const replyBox = (await page.getByText("and the colours?").boundingBox())!;
  expect((await pending.boundingBox())!.y).toBeGreaterThan(replyBox.y);
});

test("after Load more, every card appears in place and the label goes", async ({
  page,
}) => {
  await open(page);
  const more = page.getByRole("button", { name: "Load more" });
  // Load older runs until none is left (each press loads one run).
  for (let i = 0; i < 25 && (await more.count()) > 0; i++) {
    if (await more.isEnabled()) await more.click().catch(() => undefined);
    await page.waitForTimeout(700);
  }
  await expect(more).toHaveCount(0, { timeout: 10_000 });
  await expect(page.getByText("build me a Today page")).toBeVisible();
  const y = async (text: string) =>
    (await page.getByText(text, { exact: true }).first().boundingBox())!.y;
  const c1 = page.locator('[data-testid="app-card-line"][data-card-id="c1"]');
  const c2 = page.locator('[data-testid="app-card-line"][data-card-id="c2"]');
  const c3 = page.locator(
    '[data-testid="app-approval-card"][data-card-id="c3"]',
  );
  await expect(c1).toHaveCount(1);
  await expect(c2).toHaveCount(1);
  await expect(c3).toHaveCount(1);
  expect((await c1.boundingBox())!.y).toBeLessThan(
    await y("add my pull requests"),
  );
  expect((await c2.boundingBox())!.y).toBeLessThan(await y("make it denser"));
  expect((await c3.boundingBox())!.y).toBeLessThan(
    await y("thanks, tell me about the layout"),
  );
  await expect(page.getByTestId("app-card-earlier")).toHaveCount(0);
});
