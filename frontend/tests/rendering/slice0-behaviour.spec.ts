import { mkdirSync } from "fs";

import { expect, test, type Page } from "@playwright/test";

import { lowContrastText } from "./contrast-probe";

/**
 * Spec 009 Slice 0 UI:
 * - the plan (write_todos, every mode) in the chat, with its "Done when" line;
 * - Verified / Unverified under an answer, from the server's record on the
 *   final AI message (never from the reply's prose), and "Open trace";
 * - the per-run trace page (steps, tiers, cards, retries, cost, resume link);
 * - Settings → Evals (score history, runs, per-task results vs baseline);
 * - Settings → Activity log lists chat traces.
 * AA contrast in both themes.
 *
 * NO BACKEND: every API is intercepted with bodies shaped as the backend's.
 */
const THREAD = "99999999-0000-0000-0000-000000000009";
const RUN = "run-0001";
const SHOTS = process.env.SLICE0_SHOTS_DIR;

const json = (body: unknown, status = 200) => ({
  status,
  contentType: "application/json",
  body: JSON.stringify(body),
});

const verification = {
  version: 1,
  run_id: RUN,
  status: "unverified",
  done_criteria: "5 restaurants, each with a link",
  items: [
    { content: "Search for restaurants", status: "completed" },
    { content: "Check each link", status: "completed" },
  ],
  checks: [
    {
      claim: "5 restaurants named",
      verified: true,
      evidence: "web_search returned them",
    },
    {
      claim: "each has a link",
      verified: false,
      evidence: "1 link not in any tool result",
    },
  ],
  not_verified: ["The link for Zahav did not appear in a search result"],
  links: {
    verified: [
      "https://a.example/1",
      "https://b.example/2",
      "https://c.example/3",
      "https://d.example/4",
    ],
    unverified: ["https://e.example/5"],
  },
  evidence_count: 4,
};

const DISCLOSURE_BLOCK =
  "\n\nAlso, for the record:\n  - I used code_job with goal=<412 chars>, project_dir='vite-counter'.";

const trace = {
  version: 1,
  run_id: RUN,
  thread_id: THREAD,
  status: "success",
  started_at: "2026-10-26T10:00:00Z",
  finished_at: "2026-10-26T10:00:42Z",
  duration_ms: 42000,
  model: "gpt-5",
  tokens: { input: 18200, output: 2100, total: 20300 },
  llm_calls: 6,
  cost_usd: 0.044,
  resumed_from: null,
  resumes: ["run-0002"],
  done_criteria: "5 restaurants, each with a link",
  verification,
  retries: 1,
  steps: [
    {
      index: 0,
      type: "checklist",
      name: "write_todos",
      tier: 1,
      status: "ok",
      started_at: "2026-10-26T10:00:02Z",
      ended_at: "2026-10-26T10:00:02Z",
      parent: null,
      source_event: "12",
      args: "3 items",
      output: null,
      card_id: null,
    },
    {
      index: 1,
      type: "tool",
      name: "web_fetch",
      tier: 1,
      status: "error",
      started_at: "2026-10-26T10:00:05Z",
      ended_at: "2026-10-26T10:00:06Z",
      parent: null,
      source_event: "15",
      args: "url=https://pypi.org/pypi/httpx/jsonx",
      output: "404 Not Found",
      card_id: null,
    },
    {
      index: 2,
      type: "retry",
      name: "web_fetch",
      tier: 1,
      status: "ok",
      started_at: "2026-10-26T10:00:07Z",
      ended_at: "2026-10-26T10:00:08Z",
      parent: 1,
      source_event: "18",
      args: "url=https://pypi.org/pypi/httpx/json",
      output: '{"info": {"version": "0.28.1"}}',
      card_id: null,
    },
    {
      index: 3,
      type: "card",
      name: "ledger_apply",
      tier: 3,
      status: "needs_confirmation",
      started_at: "2026-10-26T10:00:20Z",
      ended_at: null,
      parent: null,
      source_event: "30",
      args: "new project Eval Kitchen Reno",
      output: null,
      card_id: "card-1",
    },
    {
      index: 4,
      type: "verify",
      name: "Done when: 5 restaurants, each with a link",
      tier: null,
      status: "unverified",
      started_at: "2026-10-26T10:00:40Z",
      ended_at: "2026-10-26T10:00:40Z",
      parent: null,
      source_event: null,
      args: null,
      output: null,
      card_id: null,
    },
  ],
  cards: [{ id: "card-1", tool: "ledger_apply", tier: 3, outcome: "executed" }],
};

const runDetail = {
  id: "h1",
  kind: "chat",
  source_id: RUN,
  event_id: null,
  thread_id: THREAD,
  started_at: "2026-10-26T10:00:00Z",
  finished_at: "2026-10-26T10:00:42Z",
  status: "success",
  error: null,
  size: 4000,
  body: { trace },
};

const evalTasks = [
  {
    id: "T01",
    title: "Philly date night, 5 with links",
    pass: true,
    live_only: false,
    baseline_pass: true,
    checks: [
      { name: "min_links(5)", pass: true, reason: "7 links, 5 hosts" },
      { name: "no_menu", pass: true, reason: "" },
    ],
    seconds: 48,
    tokens: { input: 20000, output: 2000 },
    cost_usd: 0.05,
    thread_id: THREAD,
  },
  {
    id: "T03",
    title: "Calendar this week",
    pass: true,
    live_only: true,
    baseline_pass: false,
    checks: [
      { name: "no_clarification", pass: true, reason: "no question asked" },
    ],
    seconds: 20,
    tokens: null,
    cost_usd: 0.01,
    thread_id: null,
  },
  {
    id: "T14",
    title: "Post to team chat (absent)",
    pass: false,
    live_only: false,
    baseline_pass: null,
    checks: [
      {
        name: "blocker_stated",
        pass: false,
        reason: "reply did not say what to connect",
      },
    ],
    seconds: 12,
    tokens: null,
    cost_usd: 0.009,
    thread_id: null,
  },
];
const evalRuns = [
  {
    id: "2026-10-26-real-abc1234",
    created_at: "2026-10-26T09:00:00Z",
    mode: "real",
    git_sha: "abc1234def",
    model: "gpt-5",
    trials: 1,
    passed: 14,
    total: 18,
    strict_passed: 11,
    cost_usd: 1.12,
    seconds: 900,
    regressions: [],
  },
  {
    id: "2026-10-25-mock-abc1234",
    created_at: "2026-10-25T09:00:00Z",
    mode: "mock",
    git_sha: "abc1234def",
    model: null,
    trials: 1,
    passed: 23,
    total: 23,
    strict_passed: null,
    cost_usd: 0,
    seconds: 60,
    regressions: [],
  },
  {
    id: "2026-10-24-real-e31fd85",
    created_at: "2026-10-24T09:00:00Z",
    mode: "real",
    git_sha: "e31fd85000",
    model: "gpt-5",
    trials: 1,
    passed: 7,
    total: 18,
    strict_passed: 4,
    cost_usd: 0.97,
    seconds: 1200,
    regressions: [],
  },
];

async function mockAll(
  page: Page,
  scheme: "light" | "dark",
  messagesOverride?: unknown[],
) {
  await page.addInitScript((t) => {
    try {
      localStorage.setItem("theme", t);
    } catch {}
  }, scheme);
  const state = {
    values: {
      title: "Date night",
      todos: [
        {
          content: "Done when: 5 restaurants, each with a link",
          status: "completed",
        },
        { content: "Search for restaurants", status: "completed" },
        { content: "Check each link", status: "in_progress" },
        { content: "Write the answer", status: "pending" },
      ],
      messages: messagesOverride ?? [
        { type: "human", id: "h1", content: "find 5 date-night restaurants" },
        {
          type: "ai",
          id: "a1",
          content:
            "Here are five picks: [Vetri](https://a.example/1), [Zahav](https://e.example/5).\n\nChecked: 4 of 5 links came from search results." +
            DISCLOSURE_BLOCK,
          additional_kwargs: {
            omniharness_verification: verification,
            // The policy layer's appended Tier 2 disclosure, marked for display.
            omniharness_disclosure: {
              text: DISCLOSURE_BLOCK,
              items: [
                {
                  tool: "code_job",
                  text: "I used code_job with goal=<412 chars>, project_dir='vite-counter'.",
                },
              ],
            },
          },
        },
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
  await page.route("**/api/run-history/traces/**", (route) => {
    const id = decodeURIComponent(
      new URL(route.request().url()).pathname.split("/").at(-1)!,
    );
    return id === RUN
      ? route.fulfill(json(runDetail))
      : route.fulfill(json({ detail: "No such run" }, 404));
  });
  await page.route("**/api/run-history/runs?**", (route) =>
    route.fulfill(json([{ ...runDetail, body: undefined }])),
  );
  await page.route("**/api/evals", (route) =>
    route.fulfill(
      json({
        baseline: { ...evalRuns[2], tasks: [] },
        runs: evalRuns,
        results_dir: "/repo/eval/results",
      }),
    ),
  );
  await page.route("**/api/evals/*", (route) => {
    const id = decodeURIComponent(
      new URL(route.request().url()).pathname.split("/").at(-1)!,
    );
    const run = evalRuns.find((r) => r.id === id) ?? evalRuns[0];
    return route.fulfill(json({ ...run, tasks: evalTasks }));
  });
}

/** One turn whose reply the policy layer appended a disclosure block to. */
function disclosedTurn(
  n: number,
  reply: string,
  items: [string, string, string?, boolean?][],
) {
  const block =
    "\n\nAlso, for the record:\n" +
    items.map(([, text]) => `  - ${text}`).join("\n");
  return [
    { type: "human", id: `dh${n}`, content: `request ${n}` },
    {
      type: "ai",
      id: `da${n}`,
      content: reply + block,
      additional_kwargs: {
        omniharness_disclosure: {
          text: block,
          items: items.map(([tool, text, agent, grant]) => ({
            tool,
            text,
            ...(agent ? { agent } : {}),
            ...(grant ? { grant } : {}),
          })),
        },
      },
    },
  ];
}

const DISCLOSED_TURNS = [
  ...disclosedTurn(1, "The counter app is built.", [
    ["code_job", "I used code_job with project_dir='vite-counter'."],
  ]),
  ...disclosedTurn(2, "The app is built and the tasks are added.", [
    ["code_job", "I used code_job with project_dir='site'."],
    ["ledger_apply", "I used ledger_apply on Eval Garden: Water seedlings."],
    ["write_file", "I used write_file on /mnt/user-data/outputs/notes.md."],
    ["ledger_apply", "I used ledger_apply on Eval Garden: Build trellis."],
  ]),
  ...disclosedTurn(4, "The repo is summarised and two tasks are added.", [
    ["code_job", "code_job with project_dir='site'"],
    ["ledger_apply", "ledger_apply (via Repo analyst)", "Repo analyst"],
    ["ledger_apply", "ledger_apply (via Repo analyst)", "Repo analyst"],
  ]),
  ...disclosedTurn(5, "Morning brief: two tasks added.", [
    ["ledger_apply", "ledger_apply on Eval Garden: Water", "", true],
    ["ledger_apply", "ledger_apply on Eval Garden: Prune", "", true],
  ]),
  ...disclosedTurn(3, "Three tasks are added to Eval Garden.", [
    ["ledger_apply", "I used ledger_apply on Eval Garden: Water seedlings."],
    ["ledger_apply", "I used ledger_apply on Eval Garden: Build trellis."],
    ["ledger_apply", "I used ledger_apply on Eval Garden: Harvest basil."],
  ]),
];

async function expectAA(page: Page) {
  const found = await page.evaluate(lowContrastText);
  expect(
    found,
    found
      .map((f) => `${f.ratio}/${f.need} "${f.text}" ${f.color} [${f.cls}]`)
      .join("\n"),
  ).toEqual([]);
}

async function shot(page: Page, name: string) {
  if (!SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true });
}

for (const scheme of ["light", "dark"] as const) {
  test.describe(`${scheme} theme`, () => {
    test.use({ colorScheme: scheme, viewport: { width: 1440, height: 1100 } });

    test("chat: the plan with its done-criteria, and an Unverified badge from the record", async ({
      page,
    }) => {
      await mockAll(page, scheme);
      await page.goto(`/workspace/chats/${THREAD}`, {
        waitUntil: "networkidle",
      });
      const plan = page.getByTestId("todo-list");
      await expect(plan).toBeVisible();
      await expect(page.getByTestId("todo-progress")).toHaveText("1/3 done");
      await expect(plan).toContainText("Check each link");
      // Keyboard: the header is a button that opens the list.
      const toggle = plan.getByRole("button", { name: /Plan/ });
      await toggle.focus();
      await page.keyboard.press("Enter");
      await expect(toggle).toHaveAttribute("aria-expanded", "true");
      await expect(page.getByTestId("todo-done-criteria")).toContainText(
        "Done when: 5 restaurants, each with a link",
      );

      const badge = page.getByTestId("verification-badge");
      await expect(badge).toHaveText(/Unverified/);
      await expect(badge).toHaveAttribute("data-status", "unverified");
      await badge.focus();
      await page.keyboard.press("Enter");
      const details = page.getByTestId("verification-details");
      await expect(details).toContainText("each has a link");
      await expect(details).toContainText(
        "The link for Zahav did not appear in a search result",
      );
      await expect(details).toContainText("4 found in this run");
      await expect(page.getByTestId("open-trace")).toHaveAttribute(
        "href",
        `/workspace/traces/${RUN}`,
      );
      // The disclosure block is a system note under the answer, not the
      // assistant narrating its tool calls.
      await expect(page.getByText("Also, for the record")).toHaveCount(0);
      const note = page.getByTestId("disclosure-note");
      await expect(note).toContainText("Ran without asking: code_job");
      const noteToggle = note.getByRole("button");
      await noteToggle.focus();
      await page.keyboard.press("Enter");
      await expect(noteToggle).toHaveAttribute("aria-expanded", "true");
      await expect(page.getByTestId("disclosure-details")).toContainText(
        "project_dir='vite-counter'",
      );
      await shot(page, `chat-plan-verification-${scheme}`);
      await expectAA(page);
    });

    test("disclosure note: one action, several mixed, repeats, each on one line", async ({
      page,
    }) => {
      await mockAll(page, scheme, DISCLOSED_TURNS);
      await page.goto(`/workspace/chats/${THREAD}`, {
        waitUntil: "networkidle",
      });
      await expect(page.getByText("Also, for the record")).toHaveCount(0);
      const notes = page.getByTestId("disclosure-note");
      await expect(notes).toHaveCount(5);
      await expect(notes.nth(0).getByRole("button")).toHaveText(
        "Ran without asking: code_job",
      );
      await expect(notes.nth(1).getByRole("button")).toHaveText(
        "Ran without asking: code_job, ledger_apply \u00d72, write_file",
      );
      await expect(notes.nth(2).getByRole("button")).toHaveText(
        "Ran without asking: code_job, ledger_apply \u00d72 (via Repo analyst)",
      );
      await expect(notes.nth(3).getByRole("button")).toHaveText(
        "Ran under grant: ledger_apply \u00d72",
      );
      await expect(notes.nth(4).getByRole("button")).toHaveText(
        "Ran without asking: ledger_apply \u00d73",
      );
      // Details list every disclosure in full (keyboard: Enter opens).
      for (const i of [0, 1, 2, 3, 4]) {
        const toggle = notes.nth(i).getByRole("button");
        await toggle.focus();
        await page.keyboard.press("Enter");
        await expect(toggle).toHaveAttribute("aria-expanded", "true");
      }
      await expect(
        notes.nth(1).getByTestId("disclosure-details").getByRole("listitem"),
      ).toHaveText([
        "I used code_job with project_dir='site'.",
        "I used ledger_apply on Eval Garden: Water seedlings.",
        "I used write_file on /mnt/user-data/outputs/notes.md.",
        "I used ledger_apply on Eval Garden: Build trellis.",
      ]);
      await expect(
        notes.nth(4).getByTestId("disclosure-details").getByRole("listitem"),
      ).toHaveCount(3);
      await expect(
        notes.nth(2).getByTestId("disclosure-details"),
      ).toContainText("(via Repo analyst)");
      await shot(page, `disclosure-notes-${scheme}`);
      await expectAA(page);
    });

    test("trace page: steps, tiers, retry nesting, cards, cost, resume link", async ({
      page,
    }) => {
      await mockAll(page, scheme);
      await page.goto(`/workspace/traces/${RUN}`, { waitUntil: "networkidle" });
      const view = page.getByTestId("trace-view");
      await expect(view).toBeVisible();
      await expect(page.getByTestId("trace-step")).toHaveCount(5);
      await expect(view).toContainText("gpt-5");
      await expect(view).toContainText("$0.04");
      await expect(view).toContainText("42 s");
      await expect(view).toContainText("Needs confirmation");
      await expect(view).toContainText("Tier 3");
      await expect(
        page.getByRole("link", { name: "resume run 1" }),
      ).toHaveAttribute("href", "/workspace/traces/run-0002");
      // Expand the failed fetch: its error output is shown.
      await page
        .getByRole("button", { name: "Show details of step 2" })
        .click();
      await expect(view).toContainText("404 Not Found");
      await shot(page, `trace-${scheme}`);
      await expectAA(page);
    });

    test("trace page: a run with no trace yet says so", async ({ page }) => {
      await mockAll(page, scheme);
      await page.goto(`/workspace/traces/unknown-run`, {
        waitUntil: "networkidle",
      });
      await expect(page.getByTestId("trace-missing")).toContainText(
        "No trace for this run yet",
      );
    });

    test("Settings → Evals: history, runs, per-task results against the baseline", async ({
      page,
    }) => {
      await mockAll(page, scheme);
      await page.goto(`/workspace/settings/evals`, {
        waitUntil: "networkidle",
      });
      await expect(
        page.getByRole("link", { name: "Evals", exact: true }),
      ).toHaveAttribute("aria-current", "page");
      await expect(page.getByTestId("eval-baseline")).toContainText("7/18");
      await expect(page.getByTestId("score-chart")).toBeVisible();
      await expect(page.getByTestId("eval-runs")).toContainText("14/18");
      await expect(page.getByTestId("eval-task")).toHaveCount(3);
      const failing = page.getByTestId("eval-task").filter({ hasText: "T14" });
      await expect(failing).toHaveAttribute("data-pass", "false");
      await failing.getByRole("button").click();
      await expect(page.getByTestId("eval-run")).toContainText(
        "reply did not say what to connect",
      );
      await expect(page.getByTestId("eval-run")).toContainText("live-only");
      await shot(page, `evals-${scheme}`);
      await expectAA(page);
    });

    test("Settings → Activity log links chat traces", async ({ page }) => {
      await mockAll(page, scheme);
      await page.route("**/api/run-history/settings", (route) =>
        route.fulfill(
          json({
            retention_days: 30,
            runs: 1,
            location: "/data",
            warning: null,
          }),
        ),
      );
      await page.goto(`/workspace/settings/activity`, {
        waitUntil: "networkidle",
      });
      const list = page.getByTestId("chat-traces");
      await expect(list).toBeVisible();
      await expect(list.getByRole("link").first()).toHaveAttribute(
        "href",
        `/workspace/traces/${RUN}`,
      );
    });
  });
}
