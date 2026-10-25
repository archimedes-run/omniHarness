import { expect, test, type Page } from "@playwright/test";

import { lowContrastText } from "./contrast-probe";

/**
 * Spec 009, Slice 1: a coding job's card in the chat.
 *
 * - while it runs: live steps (commands with the exit code from the event
 *   stream, file writes), cost against its budget, and Stop, which calls the
 *   stop route;
 * - when it ends: the steps fold away (and open again on request), and the
 *   card shows the status the SYSTEM decided, with its evidence (the build
 *   check's exit code, the expected files, the files changed, tests);
 * - a verified build opens in the artifact panel; an unverified job never
 *   reads as done and offers no app;
 * - a step's status comes from its exit code, never from the worker's words;
 * - every piece of text reads at WCAG AA in both themes.
 *
 * NO BACKEND: the thread's history, the job route and the stop route are
 * intercepted. Set CODE_JOB_SHOTS=<dir> to save screenshots.
 */
const THREAD = "99999999-aaaa-bbbb-cccc-dddddddddddd";
const SHOTS = process.env.CODE_JOB_SHOTS;
const NOW = Date.now();
const iso = (offset: number) => new Date(NOW + offset * 1000).toISOString();

const BRIEF = {
  goal: "Create a Vite + React counter app, build it and show it",
  project_dir: "counter-app",
  verify_command: "npm run build",
  expect_files: ["dist/index.html"],
  publish_dir: "dist",
};

const STEPS = [
  {
    seq: 1,
    at: iso(-90),
    kind: "phase",
    phase: "working",
    text: "OpenCode started in the sandbox",
  },
  {
    seq: 2,
    at: iso(-80),
    kind: "command",
    command:
      "npm create vite@latest counter-app -- --template react --no-interactive < /dev/null",
    exit_code: 0,
    status: "ok",
    output:
      "Scaffolding project in /mnt/user-data/workspace/counter-app...\nDone.",
  },
  {
    seq: 3,
    at: iso(-60),
    kind: "file",
    action: "wrote",
    path: "counter-app/src/App.jsx",
    status: "ok",
  },
  {
    seq: 4,
    at: iso(-50),
    kind: "command",
    command: "npm test",
    exit_code: 1,
    status: "error",
    output: "1 failed",
    is_test: true,
  },
  { seq: 5, at: iso(-40), kind: "message", text: "All tests passed (exit 0)." },
  {
    seq: 6,
    at: iso(-30),
    kind: "command",
    command: "npm run build",
    exit_code: 0,
    status: "ok",
    output: "dist/index.html 0.47 kB\n✓ built in 179ms",
    is_build: true,
  },
];

function job(status: string, extra: Record<string, unknown> = {}) {
  return {
    id: "job0123456789abc",
    thread_id: THREAD,
    tool_call_id: "cj1",
    title: BRIEF.goal,
    project_dir: "counter-app",
    model: "gpt-5",
    status,
    phase: status === "running" ? "working" : "done",
    budget_usd: 1.0,
    spent_usd: 0.1663,
    calls: 24,
    stop_requested: false,
    reason: null,
    result: null,
    created_at: iso(-95),
    updated_at: iso(-1),
    finished_at: status === "running" ? null : iso(-2),
    ...extra,
  };
}

const VERIFIED_RESULT = {
  status: "verified",
  reason: null,
  verify: {
    command: "npm run build",
    exit_code: 0,
    timed_out: false,
    limit_s: 600,
    seconds: 1.8,
    log_tail: "built",
  },
  expected_files: [{ path: "dist/index.html", exists: true, bytes: 471 }],
  files_changed: {
    added: ["package.json", "src/App.jsx", "src/main.jsx", "vite.config.js"],
    modified: [],
    deleted: [],
    count: 4,
  },
  worker: {
    exit_code: 0,
    commands: 3,
    failed_commands: [],
    tests: [{ command: "npm test", exit_code: 1 }],
    builds: [],
    errors: [],
    summary: "Done.",
  },
  cost_usd: 0.1663,
  budget_usd: 1,
  calls: 24,
  model: "gpt-5",
  published: {
    artifact_id: "counter-app",
    path: "/mnt/user-data/outputs/counter-app/index.html",
  },
  duration_s: 93,
};

function history(done: boolean, report: string) {
  const messages: unknown[] = [
    {
      type: "human",
      id: "h1",
      content:
        "Create a Vite + React app with a counter, build it, and show it.",
    },
    {
      type: "ai",
      id: "a1",
      content: "",
      tool_calls: [{ id: "cj1", name: "code_job", args: BRIEF }],
    },
  ];
  if (done) {
    messages.push({
      type: "tool",
      id: "t1",
      name: "code_job",
      tool_call_id: "cj1",
      content: report,
    });
    messages.push({
      type: "ai",
      id: "a2",
      content: "Here is what the coding job did.",
    });
  }
  return [
    {
      values: { title: "Counter app", messages },
      next: [],
      tasks: [],
      metadata: {},
      created_at: new Date().toISOString(),
      checkpoint: { thread_id: THREAD, checkpoint_id: "c1", checkpoint_ns: "" },
      parent_checkpoint: null,
    },
  ];
}

async function open(
  page: Page,
  scheme: "light" | "dark",
  payload: unknown,
  done: boolean,
) {
  const json = (body: unknown, status = 200) => ({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
  const stops: string[] = [];
  await page.addInitScript((t) => {
    try {
      localStorage.setItem("theme", t);
    } catch {}
  }, scheme);
  const state = history(
    done,
    "Coding job job0123456789abc (counter-app): STATUS VERIFIED",
  )[0];
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
  await page.route("**/api/threads/*/code-jobs/by-call/cj1**", (route) => {
    const after = Number(
      new URL(route.request().url()).searchParams.get("after") ?? "0",
    );
    const body = payload as { steps: { seq: number }[] };
    return route.fulfill(
      json({ ...body, steps: body.steps.filter((s) => s.seq > after) }),
    );
  });
  await page.route("**/api/threads/*/code-jobs/*/stop", (route) => {
    stops.push(route.request().method());
    return route.fulfill(json({ stopping: true, job: null }));
  });
  await page.route("**/api/threads/*/artifacts/manifests", (route) =>
    route.fulfill(
      json({
        manifests: [
          {
            id: "counter-app",
            title: "Counter app",
            type: "static_site",
            entrypoint: "index.html",
            root: ".",
            preview: { mode: "static" },
            manifest_path:
              "/mnt/user-data/outputs/counter-app/artifact_manifest.json",
            root_path: "/mnt/user-data/outputs/counter-app",
            entrypoint_path: "/mnt/user-data/outputs/counter-app/index.html",
          },
        ],
      }),
    ),
  );
  await page.route("**/api/threads/*/artifacts/**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "text/html",
      body: "<!doctype html><h1>Counter</h1><button>count is 0</button>",
    }),
  );
  await page.goto(`/workspace/chats/${THREAD}`, { waitUntil: "networkidle" });
  await expect(page.getByTestId("code-job-card")).toBeVisible();
  return stops;
}

async function aa(page: Page) {
  const low = await page.evaluate(lowContrastText);
  expect(low, JSON.stringify(low, null, 2)).toEqual([]);
}

for (const scheme of ["light", "dark"] as const) {
  test.describe(`${scheme} theme`, () => {
    test.use({ colorScheme: scheme, viewport: { width: 1440, height: 900 } });

    test("a running job shows its live steps with exit codes, its cost, and Stop", async ({
      page,
    }) => {
      const stops = await open(
        page,
        scheme,
        {
          job: job("running"),
          steps: STEPS,
          month: { spent_usd: 0.31, cap_usd: 20 },
        },
        false,
      );
      const card = page.getByTestId("code-job-card");
      await expect(card.getByTestId("code-job-status")).toHaveText("Running");
      await expect(card.getByTestId("code-job-cost")).toHaveText(
        "$0.17 of $1.00",
      );
      await expect(card.getByTestId("code-job-activity")).toContainText(
        "npm run build (exit 0)",
      );
      await expect(card.getByTestId("code-job-steps-toggle")).toHaveAttribute(
        "aria-expanded",
        "true",
      );
      const commands = card.getByTestId("code-job-step-command");
      await expect(commands).toHaveCount(3);
      // The exit code comes from the event, not from the worker's "exit 0".
      await expect(commands.nth(1)).toContainText("exit 1");
      await expect(card.getByText("Worker says (not verified):")).toBeVisible();
      await aa(page);
      if (SHOTS)
        await card.screenshot({
          path: `${SHOTS}/code-job-running-${scheme}.png`,
        });
      await card.getByTestId("code-job-stop").click();
      await expect.poll(() => stops).toEqual(["POST"]);
    });

    test("a verified job folds its steps, shows the system's evidence, and opens the app", async ({
      page,
    }) => {
      await open(
        page,
        scheme,
        {
          job: job("verified", { result: VERIFIED_RESULT }),
          steps: STEPS,
          month: { spent_usd: 0.31, cap_usd: 20 },
        },
        true,
      );
      const card = page.getByTestId("code-job-card");
      await expect(card.getByTestId("code-job-status")).toHaveText("Verified");
      await expect(card.getByTestId("code-job-stop")).toHaveCount(0);
      await expect(card.getByTestId("code-job-steps-toggle")).toHaveAttribute(
        "aria-expanded",
        "false",
      );
      const evidence = card.getByTestId("code-job-evidence");
      await expect(evidence).toContainText(
        "npm run build exited 0 (run by the system)",
      );
      await expect(evidence).toContainText(
        "dist/index.html exists (471 bytes)",
      );
      await expect(evidence).toContainText("4 files changed");
      await expect(evidence).toContainText("npm test: exit 1");
      await aa(page);
      if (SHOTS)
        await card.screenshot({
          path: `${SHOTS}/code-job-verified-${scheme}.png`,
        });
      await card.getByTestId("code-job-steps-toggle").click();
      await expect(card.getByTestId("code-job-steps")).toBeVisible();
      await card.getByTestId("code-job-open-app").click();
      // The built page opens in the artifact panel's preview.
      await expect(
        page
          .frameLocator("iframe")
          .first()
          .getByRole("button", { name: "count is 0" }),
      ).toBeVisible();
      if (SHOTS)
        await page.screenshot({ path: `${SHOTS}/code-job-app-${scheme}.png` });
    });

    test("an unverified job never reads as done and offers no app", async ({
      page,
    }) => {
      const result = {
        ...VERIFIED_RESULT,
        status: "unverified",
        reason:
          "no verification command: nothing was built or tested by the system",
        verify: null,
        expected_files: [],
        published: null,
      };
      await open(
        page,
        scheme,
        {
          job: job("unverified", { result, reason: result.reason }),
          steps: STEPS.slice(0, 3),
          month: { spent_usd: 0.31, cap_usd: 20 },
        },
        true,
      );
      const card = page.getByTestId("code-job-card");
      await expect(card.getByTestId("code-job-status")).toHaveText(
        "Unverified",
      );
      await expect(card.getByTestId("code-job-evidence")).toContainText(
        "No build check was run",
      );
      await expect(card.getByTestId("code-job-open-app")).toHaveCount(0);
      await expect(card).not.toContainText(/\bVerified\b/);
      await aa(page);
      if (SHOTS)
        await card.screenshot({
          path: `${SHOTS}/code-job-unverified-${scheme}.png`,
        });
    });
  });
}
