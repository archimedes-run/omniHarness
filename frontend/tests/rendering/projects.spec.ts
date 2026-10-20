import { expect, test, type Page, type Route } from "@playwright/test";

/**
 * Feature 005 slice 2: Projects, the Project view, the ledger card in chat,
 * attaching a chat and promoting its to-dos.
 *
 * NO BACKEND: /api/ledger and /api/confirmations are intercepted and every
 * write is recorded. The routes' own behaviour (versions, ownership, all or
 * nothing) is pytest's (tests/ledger/).
 */
const json = (body: unknown, status = 200) => ({
  status,
  contentType: "application/json",
  body: JSON.stringify(body),
});
const DAY = 24 * 60 * 60 * 1000;
const iso = (days: number) => new Date(Date.now() + days * DAY).toISOString();
const ymd = (days: number) => iso(days).slice(0, 10);

const PROJECT = {
  id: "p1",
  name: "Beta launch",
  why: "Ship the public beta by Dec 1",
  status: "active",
  context: null,
  version: 3,
  created_at: iso(-10),
  updated_at: iso(-1),
};

const VIEW = {
  project: PROJECT,
  goals: [
    {
      id: "g1",
      project_id: "p1",
      title: "Public beta live",
      definition_of_done: "anyone can sign up",
      target_date: ymd(40),
      version: 1,
      progress: { done: 1, total: 3 },
    },
  ],
  tasks: [
    {
      id: "t1",
      project_id: "p1",
      short_id: "T-1",
      title: "Landing page",
      status: "done",
      owner: { kind: "user", ref: null },
      due_date: ymd(-5),
      goal_id: "g1",
      version: 4,
      done_at: iso(-1),
    },
    {
      id: "t2",
      project_id: "p1",
      short_id: "T-2",
      title: "Waitlist form",
      status: "doing",
      owner: { kind: "agent", ref: null },
      due_date: ymd(-2),
      goal_id: "g1",
      version: 2,
      done_at: null,
    },
    {
      id: "t3",
      project_id: "p1",
      short_id: "T-3",
      title: "Announcement post",
      status: "todo",
      owner: null,
      due_date: ymd(7),
      goal_id: "g1",
      version: 1,
      done_at: null,
    },
  ],
  notes: [
    {
      id: "n1",
      decided: "Use Resend for the waitlist",
      why: "simple API",
      thread_id: null,
      created_at: iso(-3),
    },
  ],
  links: [
    {
      id: "l1",
      from_kind: "project",
      from_id: "p1",
      to_kind: "thread",
      to_ref: "thread-1",
      label: "Plan the beta",
    },
  ],
};

type Write = { method: string; path: string; body: unknown };

async function serve(
  page: Page,
  {
    projects = [{ ...PROJECT, open_tasks: 2, overdue: 1, done_tasks: 1 }],
    view = VIEW,
    status409 = false,
  } = {},
) {
  const writes: Write[] = [];
  await page.route("**/api/ledger/**", (route: Route) => {
    const req = route.request();
    const path = new URL(req.url()).pathname;
    if (req.method() !== "GET") {
      writes.push({ method: req.method(), path, body: req.postDataJSON() });
      if (status409 && req.method() === "PATCH") {
        return route.fulfill(
          json(
            {
              detail: {
                message: "this changed since you opened it",
                current: {},
              },
            },
            409,
          ),
        );
      }
      if (path.endsWith("/projects"))
        return route.fulfill(json({ ...PROJECT, id: "p2", name: "New" }, 201));
      return route.fulfill(json({}, 200));
    }
    if (path === "/api/ledger/projects") return route.fulfill(json(projects));
    if (path.startsWith("/api/ledger/projects/"))
      return route.fulfill(json(view));
    if (path.startsWith("/api/ledger/threads/")) return route.fulfill(json([]));
    return route.fulfill(json([]));
  });
  return writes;
}

test("the projects list shows each project's open and overdue counts; one primary action", async ({
  page,
}) => {
  await serve(page);
  await page.goto("/workspace/projects");
  const row = page.getByTestId("project");
  await expect(row).toHaveCount(1);
  await expect(row).toContainText("Beta launch");
  await expect(row.getByTestId("counts")).toHaveText("2 open · 1 overdue");
  await expect(page.getByRole("button", { name: "New project" })).toBeVisible();
});

test("an empty ledger says how to start", async ({ page }) => {
  await serve(page, { projects: [] });
  await page.goto("/workspace/projects");
  await expect(page.getByTestId("projects-empty")).toContainText(
    "Tell the assistant",
  );
});

test("a new project is created from the dialog", async ({ page }) => {
  const writes = await serve(page);
  await page.goto("/workspace/projects");
  await page.getByRole("button", { name: "New project" }).click();
  await page.getByLabel("Project name").fill("Rallion");
  await page.getByLabel("Why it matters").fill("Grow search traffic");
  await page.getByRole("button", { name: "Create project" }).click();
  await expect
    .poll(() => writes.map((w) => [w.method, w.path]))
    .toEqual([["POST", "/api/ledger/projects"]]);
  expect(writes[0]!.body).toEqual({
    name: "Rallion",
    why: "Grow search traffic",
  });
});

test("the project view shows goals with progress, tasks by status, decisions and linked chats", async ({
  page,
}) => {
  await serve(page);
  await page.goto("/workspace/projects/p1");
  await expect(
    page.getByRole("heading", { name: "Beta launch" }),
  ).toBeVisible();
  await expect(page.getByTestId("goal")).toContainText("1 of 3 done");
  await expect(
    page.locator('[data-group="doing"] [data-testid="task"]'),
  ).toContainText("Waitlist form");
  // Overdue is said, not only coloured; a done task's due date is not.
  await expect(
    page.locator('[data-status="doing"] [data-testid="due"]'),
  ).toContainText("overdue");
  await expect(
    page.locator('[data-status="done"] [data-testid="due"]'),
  ).toHaveCount(0);
  await expect(page.getByTestId("decision")).toContainText("Use Resend");
  await expect(
    page.getByTestId("linked-chats").getByRole("link"),
  ).toHaveAttribute("href", "/workspace/chats/thread-1");
  await expect(page.getByRole("button", { name: "Add task" })).toBeVisible();
});

test("changing a task's status is the user's edit, sent with the version it was based on", async ({
  page,
}) => {
  const writes = await serve(page);
  await page.goto("/workspace/projects/p1");
  await page.getByLabel("Status of T-3").selectOption("doing");
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0]).toEqual({
    method: "PATCH",
    path: "/api/ledger/tasks/t3",
    body: { version: 1, status: "doing" },
  });
});

test("a stale edit says so instead of overwriting", async ({ page }) => {
  await serve(page, { status409: true });
  await page.goto("/workspace/projects/p1");
  await page.getByLabel("Status of T-3").selectOption("blocked");
  await expect(
    page.getByText("This changed since you opened it"),
  ).toBeVisible();
});

test("adding a task posts it with its due date", async ({ page }) => {
  const writes = await serve(page);
  await page.goto("/workspace/projects/p1");
  await page.getByRole("button", { name: "Add task" }).click();
  await page.getByLabel("Task", { exact: true }).fill("Press kit");
  await page.getByLabel("Due date").fill("2026-11-20");
  await page
    .getByTestId("add-task")
    .getByRole("button", { name: "Add" })
    .click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0]).toEqual({
    method: "POST",
    path: "/api/ledger/projects/p1/tasks",
    body: {
      title: "Press kit",
      due_date: "2026-11-20",
      goal_id: undefined,
      owner: "me",
    },
  });
});

// ---- chat --------------------------------------------------------------------

const THREAD = "33333333-4444-5555-6666-777777777777";
const CHANGES = [
  { op: "create_project", ref: "p", name: "Beta launch", why: "Ship it" },
  {
    op: "create_task",
    project: "p",
    title: "Landing page",
    due_date: "2026-11-01",
  },
];

async function chat(
  page: Page,
  {
    todos = [] as { content: string; status: string }[],
    actions = [] as unknown[],
  } = {},
) {
  const writes: Write[] = [];
  const state = {
    values: {
      title: "Plan the beta",
      messages: [
        { type: "human", id: "h1", content: "Plan my beta" },
        { type: "ai", id: "a1", content: "Here is a plan." },
      ],
      todos,
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
  await page.route("**/api/confirmations**", (route) => {
    const req = route.request();
    if (req.method() === "POST") {
      writes.push({
        method: "POST",
        path: new URL(req.url()).pathname,
        body: req.postDataJSON(),
      });
      return route.fulfill(
        json({
          outcome: "executed",
          action_id: "new",
          message: "Done.",
          detail: {},
        }),
      );
    }
    return route.fulfill(json({ actions, readable: true, error: "" }));
  });
  await page.route("**/api/inbox/alerts", (route) =>
    route.fulfill(json({ alerts: [], waiting_count: 0 })),
  );
  await page.route("**/api/ledger/**", (route) => {
    const req = route.request();
    const path = new URL(req.url()).pathname;
    if (req.method() !== "GET") {
      writes.push({ method: req.method(), path, body: req.postDataJSON() });
      return route.fulfill(
        json(path.endsWith("/promote") ? [{}, {}] : {}, 201),
      );
    }
    if (path === "/api/ledger/projects")
      return route.fulfill(
        json([{ ...PROJECT, open_tasks: 0, overdue: 0, done_tasks: 0 }]),
      );
    return route.fulfill(json([]));
  });
  await page.goto(`/workspace/chats/${THREAD}`);
  await expect(page.getByText("Plan my beta")).toBeVisible();
  return writes;
}

const ACTION = {
  id: "a1b2c3",
  tool_name: "ledger_apply",
  plan_text: "Before I do this, please confirm…",
  targets: [
    "Create project “Beta launch” — Ship it",
    "Add task “Landing page” to p, due 2026-11-01",
  ],
  requester: "lead_agent",
  delegation_chain: [],
  expires_at: iso(1),
  thread_id: THREAD,
  threshold_targets: 10,
  requires_typed_count: false,
  withheld: false,
  arguments: { changes: CHANGES },
};

test("the ledger card lists the changes, and Edit sends the edited plan to be confirmed", async ({
  page,
}) => {
  const writes = await chat(page, { actions: [ACTION] });
  const card = page.getByTestId("pending-action");
  await expect(card).toContainText("Add to your projects");
  await expect(card.getByTestId("targets")).toContainText(
    "Create project “Beta launch”",
  );
  await card.getByTestId("edit").click();
  await card.getByLabel("Project name").fill("Public beta");
  await card.getByTestId("save-and-confirm").click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0]!.path).toBe("/api/confirmations/a1b2c3/edit");
  expect(writes[0]!.body).toEqual({
    arguments: {
      changes: [{ ...CHANGES[0], name: "Public beta" }, CHANGES[1]],
    },
    typed_count: null,
  });
});

test("a chat can be attached to a project from its header", async ({
  page,
}) => {
  const writes = await chat(page);
  await page.getByRole("button", { name: "Add to project" }).click();
  await page.getByRole("menuitem", { name: "Beta launch" }).click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0]).toEqual({
    method: "POST",
    path: "/api/ledger/links",
    body: {
      project_id: "p1",
      to_kind: "thread",
      to_ref: THREAD,
      label: "Plan the beta",
    },
  });
});

test("a chat's open to-dos can be promoted to project tasks", async ({
  page,
}) => {
  const writes = await chat(page, {
    todos: [
      { content: "Draft the post", status: "in_progress" },
      { content: "Pick a date", status: "pending" },
      { content: "Done already", status: "completed" },
    ],
  });
  await page.getByTestId("promote-todos").click();
  await expect(
    page.getByTestId("promote-items").getByRole("checkbox"),
  ).toHaveCount(3);
  await page.getByRole("button", { name: "Add 2 tasks" }).click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0]).toEqual({
    method: "POST",
    path: "/api/ledger/tasks/promote",
    body: {
      thread_id: THREAD,
      project_id: "p1",
      titles: ["Draft the post", "Pick a date"],
    },
  });
});

test("once confirmed, the card shows the result and nothing left to press", async ({
  page,
}) => {
  await chat(page, { actions: [ACTION] });
  const card = page.getByTestId("pending-action");
  await card.getByTestId("confirm").click();
  await expect(card.getByTestId("resolve-message")).toContainText("Done.");
  await expect(card.getByTestId("confirm")).toHaveCount(0);
  await expect(card.getByTestId("edit")).toHaveCount(0);
});
