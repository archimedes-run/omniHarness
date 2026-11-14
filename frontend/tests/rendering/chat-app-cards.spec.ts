import { expect, test, type Page } from "@playwright/test";

import { EIGHT_PLUS, json, stub, THREAD } from "./chat-bar-stubs";
import { lowContrastText } from "./contrast-probe";

/**
 * App cards in the build chat (app "today", versions 1 to 4):
 *
 * 1. each card sits right after the turn whose job registered its version,
 *    oldest first; a decided or replaced card is one line with a disclosure;
 *    only the newest undecided card is open;
 * 2. the open card shows the owner's own request ("You asked:", clipped at a
 *    word) and the assistant's description clipped at a word;
 * 3. the words fit the state and name the version served now;
 * 4. scrolled to the end, the last (tall) card ends above the chat bar.
 *
 * NO BACKEND: the thread, the cards and the app list are intercepted.
 */

const LONG_REQUEST =
  "Make the inbox tile blue and put the calendar first, then show how many reviews are waiting on me with a small chart, and keep the layout readable on my phone when I am travelling next week";
// 300 characters, cut mid-word: as the gateway stored descriptions before
// it clipped at a word.
const LONG_DESCRIPTION = (
  "Moves the calendar first and recolours the inbox tile; adds a review count with a sparkline; keeps the 360 px layout; renames the tiles to match the request; tightens spacing between the cards on small screens; checks every state in both themes; documents the change in the notes; enforcing " +
  "everything else"
).slice(0, 300);

const job = (n: number, version: number, card?: string) => [
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
    content: `Job done.\n- App registered by the system: id today, version ${version}${card ? ` (card ${card})` : ""}; it is offered to the person.`,
  },
  { type: "ai", id: `d${n}`, content: `Version ${version} is ready.` },
];

const MESSAGES = [
  { type: "human", id: "h1", content: "build me a Today page" },
  ...job(1, 1),
  { type: "human", id: "h2", content: "add my pull requests" },
  ...job(2, 2),
  { type: "human", id: "h3", content: "make it denser" },
  ...job(3, 3, "c3"),
  { type: "human", id: "h4", content: LONG_REQUEST },
  ...job(4, 4, "c4"),
];

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
  shots: [],
};
const CARDS = [
  // Newest first, as the gateway lists them.
  {
    ...base,
    id: "c4",
    version: 4,
    kind: "version",
    status: "pending",
    keeps_version: 2,
    description: LONG_DESCRIPTION,
    request_words: LONG_REQUEST,
    created_at: "2026-11-14T10:04:00Z",
    resolved_at: null,
  },
  {
    ...base,
    id: "c3",
    version: 3,
    kind: "version",
    status: "superseded",
    keeps_version: 2,
    description: "Denser.",
    request_words: "make it denser",
    created_at: "2026-11-14T10:03:00Z",
    resolved_at: null,
  },
  {
    ...base,
    id: "c2",
    version: 2,
    kind: "version",
    status: "approved",
    keeps_version: 1,
    description: "Adds pull requests.",
    request_words: "add my pull requests",
    created_at: "2026-11-14T10:02:00Z",
    resolved_at: "2026-11-14T10:02:30Z",
  },
  {
    ...base,
    id: "c1",
    version: 1,
    kind: "access",
    status: "approved",
    keeps_version: null,
    created_at: "2026-11-14T10:01:00Z",
    resolved_at: "2026-11-14T10:01:30Z",
  },
];

async function open(page: Page) {
  await stub(page, EIGHT_PLUS);
  const state = {
    values: { title: "Today app", messages: MESSAGES },
    next: [],
    tasks: [],
    metadata: {},
    created_at: new Date().toISOString(),
    checkpoint: { thread_id: THREAD, checkpoint_id: "c1", checkpoint_ns: "" },
    parent_checkpoint: null,
  };
  await page.route("**/api/langgraph/**", (route) => {
    const url = route.request().url();
    if (url.includes("/history")) return json(route, [state]);
    if (url.includes("/runs") || url.includes("/search"))
      return json(route, []);
    return json(route, state);
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
          updated_at: "2026-11-14T10:00:00Z",
          last_opened_at: null,
          pending_version: 4,
        },
      ],
    }),
  );
  await page.goto(`/workspace/chats/${THREAD}`, { waitUntil: "networkidle" });
  await expect(page.getByText("build me a Today page")).toBeVisible();
}

const top = async (page: Page, selector: string) =>
  (await page.locator(selector).first().boundingBox())!.y;

test("each card follows the turn that registered it, oldest first; only the newest undecided is open", async ({
  page,
}) => {
  await open(page);
  const lines = page.getByTestId("app-card-line");
  await expect(lines).toHaveCount(3);
  await expect(lines.nth(0)).toContainText("app access allowed");
  await expect(lines.nth(1)).toContainText("Version 2 — in use since");
  await expect(lines.nth(2)).toContainText("Version 3 — replaced by version 4");
  const cards = page.getByTestId("app-approval-card");
  await expect(cards).toHaveCount(1);
  await expect(cards.first()).toHaveAttribute("data-card-id", "c4");
  // Placement: v1 above "add my pull requests", v2 above "make it denser",
  // v3 above the long request, v4 after the last turn.
  const y = async (text: string) =>
    (await page.getByText(text, { exact: true }).first().boundingBox())!.y;
  const line = async (i: number) => (await lines.nth(i).boundingBox())!.y;
  expect(await line(0)).toBeLessThan(await y("add my pull requests"));
  expect(await line(0)).toBeGreaterThan(await y("build me a Today page"));
  expect(await line(1)).toBeLessThan(await y("make it denser"));
  expect(await line(2)).toBeLessThan(await y(LONG_REQUEST));
  expect(await top(page, '[data-card-id="c4"]')).toBeGreaterThan(
    await y(LONG_REQUEST),
  );
});

test("the open card: the owner's request and the description, clipped at a word; words for its state", async ({
  page,
}) => {
  await open(page);
  const card = page.locator(
    '[data-testid="app-approval-card"][data-card-id="c4"]',
  );
  const request = card.getByTestId("app-card-request");
  await expect(request).toContainText("You asked:");
  const shown = (await request.locator("p").nth(1).innerText())
    .replace(/Show all$/, "")
    .trim();
  expect(shown.endsWith("…")).toBe(true);
  expect(LONG_REQUEST.startsWith(shown.slice(0, -1))).toBe(true);
  expect(LONG_REQUEST[shown.length - 1]).toBe(" ");
  await request.getByRole("button", { name: "Show all" }).click();
  await expect(request).toContainText(LONG_REQUEST);
  const description = await card
    .getByTestId("app-card-description")
    .locator("blockquote")
    .innerText();
  expect(description.endsWith("…")).toBe(true);
  // Never a cut word: whole words of the original, then the ellipsis.
  expect(description).not.toContain("everythin");
  expect(LONG_DESCRIPTION.startsWith(description.slice(0, -1))).toBe(true);
  await expect(card.getByTestId("app-card-state")).toHaveText(
    "Version 2 keeps running until you choose.",
  );
  await expect(card.getByTestId("app-card-checks")).toContainText(
    "version 2, the version you use now",
  );
});

test("a decided card, opened, says what happened and nothing stale", async ({
  page,
}) => {
  await open(page);
  await page.getByTestId("app-card-line").nth(1).click();
  const card = page.locator(
    '[data-testid="app-approval-card"][data-card-id="c2"]',
  );
  await expect(card.getByTestId("app-card-state")).toHaveText(
    /^In use since .+\. Version 1 is in History\.$/,
  );
  await expect(card).not.toContainText("keeps running until you choose");
  await expect(card.getByTestId("app-card-use-version")).toHaveCount(0);
});

for (const scheme of ["light", "dark"] as const) {
  for (const width of [1280, 390]) {
    test(`the last card ends above the chat bar, and all text meets AA (${scheme}, ${width} px)`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: 800 });
      await page.emulateMedia({ colorScheme: scheme });
      await page.addInitScript((t) => {
        try {
          localStorage.setItem("theme", t);
        } catch {}
      }, scheme);
      await open(page);
      await page.getByTestId("message-list-spacer").evaluate((spacer) => {
        let el: HTMLElement | null = spacer.parentElement;
        while (el && !(el.scrollHeight > el.clientHeight + 1)) {
          el = el.parentElement;
        }
        el?.scrollTo({ top: el.scrollHeight });
      });
      await page.waitForTimeout(500);
      const card = (await page
        .locator('[data-testid="app-approval-card"][data-card-id="c4"]')
        .boundingBox())!;
      const bar = (await page.getByTestId("chat-bar").boundingBox())!;
      expect(
        card.y + card.height,
        `card ends at ${card.y + card.height}, bar starts at ${bar.y}`,
      ).toBeLessThanOrEqual(bar.y);
      const found = await page.evaluate(lowContrastText);
      expect(
        found,
        found
          .map((f) => `${f.ratio}/${f.need} "${f.text}" ${f.color} [${f.cls}]`)
          .join("\n"),
      ).toEqual([]);
    });
  }
}

/*
 * The real thread's shape (app "today", v4 in use): cards from before the
 * gateway kept the request (no request_words, no shots); the first job's
 * report has no registration line (its job record says version 1); v2's
 * report uses older wording; v4's description is the job title cut at 80.
 */
const MARK = { omniharness_user_turn: true };
const TITLE_CUT =
  "Fix specified defects in Today app without changing structure or sources; enforc";
const OLD_MESSAGES = [
  {
    type: "human",
    id: "r1",
    content: "build me a Today page",
    additional_kwargs: MARK,
  },
  {
    type: "ai",
    id: "ra1",
    content: "",
    tool_calls: [{ name: "code_job", args: {}, id: "rj1" }],
  },
  {
    type: "tool",
    id: "rt1",
    name: "code_job",
    tool_call_id: "rj1",
    content: "Job done. The app is ready.",
  },
  { type: "ai", id: "rd1", content: "Your Today page is built." },
  {
    type: "human",
    id: "r2",
    content: "add my pull requests",
    additional_kwargs: MARK,
  },
  {
    type: "ai",
    id: "ra2",
    content: "",
    tool_calls: [{ name: "code_job", args: {}, id: "rj2" }],
  },
  {
    type: "tool",
    id: "rt2",
    name: "code_job",
    tool_call_id: "rj2",
    content:
      "- App registered by the system: id today, version 2. Offered as a new version.",
  },
  { type: "ai", id: "rd2", content: "Version 2 is ready." },
  // Injected by the system: human-shaped, never the person's words.
  { type: "human", id: "rx", content: "SYSTEM REMINDER: check your todo list" },
  {
    type: "human",
    id: "r3",
    content: "make it denser",
    additional_kwargs: MARK,
  },
  {
    type: "ai",
    id: "ra3",
    content: "",
    tool_calls: [{ name: "code_job", args: {}, id: "rj3" }],
  },
  {
    type: "tool",
    id: "rt3",
    name: "code_job",
    tool_call_id: "rj3",
    content: "- App registered by the system: id today, version 3; offered",
  },
  { type: "ai", id: "rd3", content: "Version 3 is ready." },
  {
    type: "human",
    id: "r4",
    content: "Fix the defects you found, keep the structure and the sources",
    additional_kwargs: MARK,
  },
  {
    type: "ai",
    id: "ra4",
    content: "",
    tool_calls: [{ name: "code_job", args: {}, id: "rj4" }],
  },
  {
    type: "tool",
    id: "rt4",
    name: "code_job",
    tool_call_id: "rj4",
    content: "- App registered by the system: id today, version 4; offered",
  },
  { type: "ai", id: "rd4", content: "Version 4 is ready." },
];
const old = (over: Record<string, unknown>) => {
  const card: Record<string, unknown> = { ...base, ...over };
  delete card.request_words;
  delete card.shots;
  return card;
};
const OLD_CARDS = [
  old({
    id: "o4",
    version: 4,
    kind: "version",
    status: "approved",
    keeps_version: 2,
    description: TITLE_CUT,
    created_at: "2026-11-14T00:40:00Z",
    resolved_at: "2026-11-14T00:45:00Z",
  }),
  old({
    id: "o3",
    version: 3,
    kind: "version",
    status: "superseded",
    keeps_version: 2,
    description: "Denser.",
    created_at: "2026-11-14T00:20:00Z",
    resolved_at: null,
  }),
  old({
    id: "o2",
    version: 2,
    kind: "version",
    status: "approved",
    keeps_version: 1,
    description: "Pull requests.",
    created_at: "2026-11-14T00:05:00Z",
    resolved_at: "2026-11-14T00:06:00Z",
  }),
  old({
    id: "o1",
    version: 1,
    kind: "access",
    status: "approved",
    keeps_version: null,
    created_at: "2026-11-13T23:50:00Z",
    resolved_at: "2026-11-13T23:51:00Z",
  }),
];

function jobPayload(callId: string, version: number) {
  const at = "2026-11-14T00:00:00Z";
  return {
    job: {
      id: `job-${callId}`,
      thread_id: THREAD,
      tool_call_id: callId,
      title: version === 4 ? TITLE_CUT : `Today v${version}`,
      project_dir: "today",
      model: "m",
      status: "verified",
      phase: "done",
      budget_usd: 1,
      spent_usd: 0.1,
      calls: 3,
      stop_requested: false,
      reason: null,
      result: {
        status: "verified",
        reason: null,
        app_registration: {
          app_id: "today",
          version,
          name: "Today",
          needs_approval: true,
          url: "/workspace/apps/today",
        },
      },
      created_at: at,
      updated_at: at,
      finished_at: at,
    },
    steps: [],
    month: { spent_usd: 0.4, cap_usd: 20 },
  };
}

async function openOld(page: Page) {
  await stub(page, EIGHT_PLUS);
  const state = {
    values: { title: "Today app", messages: OLD_MESSAGES },
    next: [],
    tasks: [],
    metadata: {},
    created_at: new Date().toISOString(),
    checkpoint: { thread_id: THREAD, checkpoint_id: "c1", checkpoint_ns: "" },
    parent_checkpoint: null,
  };
  await page.route("**/api/langgraph/**", (route) => {
    const url = route.request().url();
    if (url.includes("/history")) return json(route, [state]);
    if (url.includes("/runs") || url.includes("/search"))
      return json(route, []);
    return json(route, state);
  });
  await page.route("**/api/confirmations", (route) =>
    json(route, { actions: [], readable: true, error: "" }),
  );
  await page.route("**/api/apps/approvals*", (route) =>
    json(route, { cards: OLD_CARDS }),
  );
  await page.route("**/api/threads/*/code-jobs/by-call/*", (route) => {
    const id = new URL(route.request().url()).pathname.split("/").pop()!;
    return json(route, jobPayload(id, Number(id.slice(2))));
  });
  await page.route(/\/api\/apps(\?|$)/, (route) =>
    json(route, {
      apps: [
        {
          id: "today",
          name: "Today",
          description: "",
          current_version: 4,
          manifest_hash: "a".repeat(64),
          status: "approved",
          pinned: false,
          updated_at: "2026-11-14T10:00:00Z",
          last_opened_at: null,
          pending_version: null,
        },
      ],
    }),
  );
  await page.goto(`/workspace/chats/${THREAD}`, { waitUntil: "networkidle" });
  await expect(page.getByText("build me a Today page")).toBeVisible();
}

test.describe("the real thread's shape (old cards, v4 in use)", () => {
  test("the access card follows the first job's turn, not the end", async ({
    page,
  }) => {
    await openOld(page);
    const access = page.locator(
      '[data-testid="app-card-line"][data-card-id="o1"]',
    );
    await expect(access).toContainText("app access allowed");
    const y = async (text: string) =>
      (await page.getByText(text, { exact: true }).first().boundingBox())!.y;
    const ay = (await access.boundingBox())!.y;
    expect(ay).toBeGreaterThan(await y("build me a Today page"));
    expect(ay).toBeLessThan(await y("add my pull requests"));
    // All four cards in order, the access card first.
    await expect(page.getByTestId("app-card-line")).toHaveCount(4);
    const ids = await page
      .getByTestId("app-card-line")
      .evaluateAll((els) => els.map((e) => e.getAttribute("data-card-id")));
    expect(ids).toEqual(["o1", "o2", "o3", "o4"]);
  });

  test("v4 opened: the request from the thread, the title cut back to a word", async ({
    page,
  }) => {
    await openOld(page);
    await page
      .locator('[data-testid="app-card-line"][data-card-id="o4"]')
      .click();
    const card = page.locator(
      '[data-testid="app-approval-card"][data-card-id="o4"]',
    );
    await expect(card.getByTestId("app-card-request")).toContainText(
      "Fix the defects you found, keep the structure and the sources",
    );
    const description = await card
      .getByTestId("app-card-description")
      .locator("blockquote")
      .innerText();
    expect(description).toBe(
      "Fix specified defects in Today app without changing structure or sources…",
    );
    // v3's request is the person's message, not the injected reminder.
    await page
      .locator('[data-testid="app-card-line"][data-card-id="o3"]')
      .click();
    await expect(
      page
        .locator('[data-testid="app-approval-card"][data-card-id="o3"]')
        .getByTestId("app-card-request"),
    ).toContainText("make it denser");
  });

  test("each job card says the live state of the version it registered", async ({
    page,
  }) => {
    await openOld(page);
    const states = page.getByTestId("code-job-app-state");
    await expect(states).toHaveCount(4);
    await expect(states).toHaveText([
      " — replaced by version 4",
      " — replaced by version 4",
      " — replaced by version 4",
      " — in use",
    ]);
    await expect(page.locator("body")).not.toContainText("needs your approval");
  });

  for (const scheme of ["light", "dark"] as const) {
    for (const width of [1280, 390]) {
      test(`AA and nothing under the chat bar (${scheme}, ${width} px)`, async ({
        page,
      }) => {
        await page.setViewportSize({ width, height: 800 });
        await page.emulateMedia({ colorScheme: scheme });
        await page.addInitScript((t) => {
          try {
            localStorage.setItem("theme", t);
          } catch {}
        }, scheme);
        await openOld(page);
        await page
          .locator('[data-testid="app-card-line"][data-card-id="o4"]')
          .click();
        await page.getByTestId("message-list-spacer").evaluate((spacer) => {
          let el: HTMLElement | null = spacer.parentElement;
          while (el && !(el.scrollHeight > el.clientHeight + 1)) {
            el = el.parentElement;
          }
          el?.scrollTo({ top: el.scrollHeight });
        });
        await page.waitForTimeout(400);
        const bar = (await page.getByTestId("chat-bar").boundingBox())!;
        const last = (await page
          .getByText("Version 4 is ready.")
          .boundingBox())!;
        expect(last.y + last.height).toBeLessThanOrEqual(bar.y);
        const found = await page.evaluate(lowContrastText);
        expect(
          found,
          found
            .map(
              (f) => `${f.ratio}/${f.need} "${f.text}" ${f.color} [${f.cls}]`,
            )
            .join("\n"),
        ).toEqual([]);
      });
    }
  }
});
