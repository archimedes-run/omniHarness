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
 *   check's exit code, the expected files, the files changed, tests, and
 *   any model calls that cost more than was reserved for them);
 * - a verified build opens in the artifact panel; an unverified job never
 *   reads as done and offers no app;
 * - a step's status comes from its exit code, never from the worker's words;
 * - the system's layout check of a built app shows as evidence: "fits" on a
 *   pass, each failure on a fail; an app that fails it is still offered,
 *   labelled "Open the app (layout check failed)";
 * - a job that finishes while the person watches keeps "Open the app" above
 *   the floating chat bar;
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
  layout: {
    outcome: "pass",
    widths: [360, 560, 1280],
    mode: "enforce",
    failures: [],
    warnings: [],
    error: null,
    seconds: 6.2,
  },
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

function history(done: boolean, report: string, mixed = false) {
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
      tool_calls: [
        { id: "cj1", name: "code_job", args: BRIEF },
        ...(mixed
          ? [
              {
                id: "s1",
                name: "task",
                args: {
                  subagent_type: "general-purpose",
                  description: "Check the licence of the template",
                  prompt: "Check it",
                },
              },
            ]
          : []),
      ],
    },
  ];
  if (done && mixed) {
    messages.push({
      type: "tool",
      id: "t2",
      name: "task",
      tool_call_id: "s1",
      content: "Task Succeeded. Result: MIT.",
    });
  }
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
  mixed = false,
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
    mixed,
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
          job: job("verified", {
            result: { ...VERIFIED_RESULT, over_reservation_calls: 2 },
          }),
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
      await expect(card.getByTestId("code-job-layout")).toHaveText(
        "Layout check: fits 360 / 560 / 1280 px (run by the system)",
      );
      await expect(evidence).toContainText("4 files changed");
      await expect(evidence).toContainText("npm test: exit 1");
      // Calls that cost more than was reserved for them are shown.
      await expect(card.getByTestId("code-job-over-reservation")).toHaveText(
        "2 model calls cost more than the system had reserved for them.",
      );
      await aa(page);
      if (SHOTS)
        await card.screenshot({
          path: `${SHOTS}/code-job-verified-${scheme}.png`,
        });
      await card.getByTestId("code-job-steps-toggle").click();
      await expect(card.getByTestId("code-job-steps")).toBeVisible();
      await expect(card.getByTestId("code-job-open-app")).toHaveText(
        "Open the app",
      );
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

    test("a coding job made beside another tool call keeps that call's card", async ({
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
        true,
      );
      const card = page.getByTestId("code-job-card");
      await expect(card.getByTestId("code-job-status")).toHaveText("Verified");
      // The other call (a subagent task) is still shown, with its result.
      await expect(
        page.getByText("Check the licence of the template"),
      ).toBeVisible();
      await aa(page);
      if (SHOTS)
        await page.screenshot({
          path: `${SHOTS}/code-job-mixed-${scheme}.png`,
        });
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

    test("a failed layout check lists each failure, is not verified, and still offers the app, marked", async ({
      page,
    }) => {
      const failures = [
        "overflows sideways at 360 px by 412 px (sticking out: div.col in div.board)",
        "chart clipped: svg in div.donut (cut off 12 px on the left) at 360, 560 px",
      ];
      const reason =
        "the layout check failed: overflows sideways at 360 px by 412 px; a chart is cut off by 12 px at 360, 560 px";
      const result = {
        ...VERIFIED_RESULT,
        status: "unverified",
        reason,
        layout: {
          ...VERIFIED_RESULT.layout,
          outcome: "fail",
          failures,
          warnings: [
            "chart labels may be cut: svg in div.bars (8 px past the right) at 360 px",
          ],
        },
        published: VERIFIED_RESULT.published,
        fix_of: "0123456789abcdef",
      };
      await open(
        page,
        scheme,
        {
          job: job("unverified", { result, reason }),
          steps: STEPS,
          month: { spent_usd: 0.31, cap_usd: 20 },
        },
        true,
      );
      const card = page.getByTestId("code-job-card");
      await expect(card.getByTestId("code-job-status")).toHaveText(
        "Unverified",
      );
      const layout = card.getByTestId("code-job-layout");
      await expect(layout).toHaveAttribute("data-outcome", "fail");
      await expect(layout).toContainText(
        "Layout check failed at 360 / 560 / 1280 px (run by the system)",
      );
      await expect(
        card.getByTestId("code-job-layout-failures").getByRole("listitem"),
      ).toHaveText(failures);
      await expect(card.getByTestId("code-job-layout-warnings")).toContainText(
        "Warning (not counted): chart labels may be cut",
      );
      await expect(layout.getByLabel("failed", { exact: true })).toBeVisible();
      // Still shown, so the person can look; the button says the check failed.
      await expect(card.getByTestId("code-job-open-app")).toHaveText(
        "Open the app (layout check failed)",
      );
      await expect(card.getByTestId("code-job-fix-of")).toContainText(
        "The automatic fix of an earlier job's layout failures",
      );
      await expect(card).not.toContainText(/\bVerified\b/);
      await aa(page);
      if (SHOTS)
        await card.screenshot({
          path: `${SHOTS}/code-job-layout-failed-${scheme}.png`,
        });
    });

    test("a layout check whose result could not be read is counted and says so", async ({
      page,
    }) => {
      const reason =
        "the layout check gave no answer: the check left no readable result";
      const result = {
        ...VERIFIED_RESULT,
        status: "unverified",
        reason,
        layout: {
          ...VERIFIED_RESULT.layout,
          outcome: "error",
          error: "the check left no readable result",
          error_code: "unreadable",
          counted: true,
        },
      };
      await open(
        page,
        scheme,
        {
          job: job("unverified", { result, reason }),
          steps: STEPS,
          month: { spent_usd: 0.31, cap_usd: 20 },
        },
        true,
      );
      const card = page.getByTestId("code-job-card");
      await expect(card.getByTestId("code-job-layout")).toHaveText(
        "Layout check gave no answer (the check left no readable result; counted: not verified)",
      );
      await expect(card.getByTestId("code-job-open-app")).toHaveText(
        "Open the app (layout not checked)",
      );
      await aa(page);
    });

    test("a job that finishes while watched keeps Open the app above the chat bar", async ({
      page,
    }) => {
      await page.setViewportSize({ width: 1280, height: 560 });
      const many = Array.from({ length: 40 }, (_, i) => ({
        seq: 100 + i,
        at: iso(-29 + i / 2),
        kind: "command",
        command: `npm run step-${i}`,
        exit_code: 0,
        status: "ok",
        output: "ok",
      }));
      const month = { spent_usd: 0.31, cap_usd: 20 };
      let current: unknown = {
        job: job("running"),
        steps: [...STEPS, ...many],
        month,
      };
      await open(page, scheme, current, false);
      await page.route("**/api/threads/*/code-jobs/by-call/cj1**", (route) => {
        const after = Number(
          new URL(route.request().url()).searchParams.get("after") ?? "0",
        );
        const body = current as { steps: { seq: number }[] };
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            ...body,
            steps: body.steps.filter((s) => s.seq > after),
          }),
        });
      });
      const card = page.getByTestId("code-job-card");
      await expect(card.getByTestId("code-job-steps")).toBeVisible();
      // The person folds the steps and scrolls up a little while it runs.
      await card.getByTestId("code-job-steps-toggle").click();
      await page.waitForTimeout(600);
      const box = (await card.boundingBox())!;
      await page.mouse.move(box.x + box.width / 2, box.y + 20);
      await page.mouse.wheel(0, -60);
      await page.waitForTimeout(400);
      current = {
        job: job("verified", { result: VERIFIED_RESULT }),
        steps: [...STEPS, ...many],
        month,
      };
      const button = card.getByTestId("code-job-open-app");
      await expect(button).toBeVisible();
      // Visible means clear of the floating chat bar, with no scrolling by the person.
      await expect
        .poll(
          async () => {
            const b = await button.boundingBox();
            const bar = await page.getByTestId("chat-bar").boundingBox();
            return b && bar ? Math.round(bar.y - (b.y + b.height)) : null;
          },
          { timeout: 5000 },
        )
        .toBeGreaterThanOrEqual(16);
      if (SHOTS)
        await page.screenshot({
          path: `${SHOTS}/code-job-finished-in-view-${scheme}.png`,
        });
    });
  });
}
