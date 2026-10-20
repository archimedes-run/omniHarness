import { expect, test, type Page } from "@playwright/test";

/**
 * Feature 006, the Tasks panel (Tasks.dc.html): projects and their tasks from
 * the Feature 005 ledger, with owners, status and dates. NO BACKEND: the
 * ledger routes are intercepted; the routes themselves are pytest's
 * (tests/ledger, through create_app()).
 */
const json = (body: unknown, status = 200) => ({
  status,
  contentType: "application/json",
  body: JSON.stringify(body),
});
const now = () => new Date().toISOString();
const daysAgo = (n: number) =>
  new Date(Date.now() - n * 86400000).toISOString();

const project = (id: string, name: string, open: number, updated = now()) => ({
  id,
  name,
  why: null,
  status: "active",
  context: null,
  version: 1,
  created_at: updated,
  updated_at: updated,
  open_tasks: open,
  overdue: 0,
  done_tasks: 0,
});

const task = (id: string, title: string, patch: object = {}) => ({
  id,
  project_id: "p1",
  short_id: id.toUpperCase(),
  title,
  status: "todo",
  owner: null,
  due_date: null,
  goal_id: null,
  version: 3,
  done_at: null,
  ...patch,
});

const VIEW = {
  project: project("p1", "OmniHarness", 4),
  goals: [
    {
      id: "g1",
      project_id: "p1",
      title: "Feature 005 Project Ledger shipped",
      definition_of_done: "merged",
      target_date: null,
      version: 1,
      progress: { done: 1, total: 5 },
    },
  ],
  tasks: [
    task("t1", "Codex adapter for the session watcher", {
      status: "blocked",
      owner: { kind: "agent", ref: "codex" },
    }),
    task("t2", "Native todo lists", {
      status: "doing",
      owner: { kind: "agent", ref: "claude-code" },
    }),
    task("t3", "Review slices 1 and 2", {
      owner: { kind: "user", ref: null },
      due_date: "2030-10-21",
    }),
    task("t4", "Live Tier 3 check"),
    task("t5", "Phase 2.6 polish", { status: "done", done_at: daysAgo(1) }),
    task("t6", "Old thing", { status: "done", done_at: daysAgo(30) }),
    task("t7", "Dropped idea", { status: "dropped" }),
  ],
  notes: [
    {
      id: "n1",
      decided: "Ship the ledger before evidence",
      why: null,
      thread_id: null,
      created_at: now(),
    },
  ],
  links: [
    {
      id: "l1",
      from_kind: "task",
      from_id: "t4",
      to_kind: "thread",
      to_ref: "th1",
      label: null,
    },
  ],
};

async function serve(page: Page) {
  const writes: { method: string; url: string; body: unknown }[] = [];
  await page.route("**/api/ledger/projects", (route) => {
    if (route.request().method() === "POST") {
      writes.push({
        method: "POST",
        url: route.request().url(),
        body: route.request().postDataJSON(),
      });
      return route.fulfill(json(project("p9", "New one", 0), 201));
    }
    return route.fulfill(
      json([
        project("p1", "OmniHarness", 4),
        project("p2", "HackMIT 2026 judging", 1, daysAgo(3)),
      ]),
    );
  });
  await page.route("**/api/ledger/projects/p1", (route) =>
    route.fulfill(json(VIEW)),
  );
  await page.route("**/api/ledger/projects/p2", (route) =>
    route.fulfill(
      json({
        ...VIEW,
        project: project("p2", "HackMIT 2026 judging", 1),
        goals: [],
        tasks: [task("h1", "Score the finalists", { project_id: "p2" })],
        links: [],
        notes: [],
      }),
    ),
  );
  await page.route("**/api/ledger/projects/p9", (route) =>
    route.fulfill(
      json({
        project: project("p9", "New one", 0),
        goals: [],
        tasks: [],
        notes: [],
        links: [],
      }),
    ),
  );
  await page.route("**/api/ledger/projects/*/tasks", (route) => {
    writes.push({
      method: "POST",
      url: route.request().url(),
      body: route.request().postDataJSON(),
    });
    return route.fulfill(json(task("t9", "x"), 201));
  });
  await page.route("**/api/ledger/tasks/*", (route) => {
    writes.push({
      method: route.request().method(),
      url: route.request().url(),
      body: route.request().postDataJSON(),
    });
    return route.fulfill(json(task("t3", "x", { version: 4 })));
  });
  await page.route("**/threads/search", (route) =>
    route.fulfill(
      json([
        {
          thread_id: "th1",
          updated_at: now(),
          values: { title: "Calendar cleanup" },
          metadata: {},
        },
      ]),
    ),
  );
  await page.goto("/workspace/chats?panel=tasks");
  const sheet = page.getByTestId("panel-sheet");
  await expect(sheet.getByTestId("project-pane")).toBeVisible();
  return { sheet, writes };
}

const row = (page: Page, title: string) =>
  page.getByTestId("task").filter({ hasText: title });

test("the panel opens on the latest project, with its goal and progress", async ({
  page,
}) => {
  const { sheet } = await serve(page);

  await expect(
    sheet.getByRole("button", { name: /OmniHarness/ }),
  ).toHaveAttribute("aria-current", "true");
  await expect(
    sheet.getByRole("button", { name: /All open tasks/ }),
  ).toContainText("5");
  await expect(
    sheet.getByRole("heading", { name: "OmniHarness" }),
  ).toBeVisible();
  // Dropped tasks are not part of the plan: 2 of 6.
  await expect(sheet.getByTestId("project-goal")).toHaveText(
    "Goal: Feature 005 Project Ledger shipped · 2 of 6 tasks done",
  );
  await expect(sheet.getByRole("progressbar")).toHaveAttribute(
    "aria-valuenow",
    "33",
  );
});

test("tasks are grouped as on the board, with owners, status and dates", async ({
  page,
}) => {
  await serve(page);

  await expect(page.getByTestId("group-progress")).toContainText("In progress");
  await expect(
    page.getByTestId("group-progress").getByTestId("task"),
  ).toHaveCount(2);
  await expect(page.getByTestId("group-todo").getByTestId("task")).toHaveCount(
    2,
  );
  await expect(page.getByTestId("group-done")).toContainText("Done this week");
  await expect(page.getByTestId("group-done")).not.toContainText("Old thing");
  await expect(page.getByText("Dropped idea")).toHaveCount(0);

  const codex = row(page, "Codex adapter");
  await expect(codex.getByTestId("owner")).toContainText("Codex");
  await expect(codex.getByRole("img", { name: /logo/ })).toBeVisible();
  await expect(codex).toContainText("Blocked");
  await expect(row(page, "Native todo lists")).toContainText("Doing");
  await expect(row(page, "Native todo lists").getByTestId("owner")).toHaveText(
    "Claude Code",
  );
  await expect(row(page, "Review slices")).toContainText("You");
  await expect(row(page, "Review slices").getByTestId("due")).toHaveText(
    "Mon, Oct 21",
  );
  await expect(row(page, "Live Tier 3").getByTestId("due")).toHaveText(
    "No date",
  );
  await expect(row(page, "Live Tier 3")).toContainText(
    "Added from chat “Calendar cleanup”",
  );
});

test("evidence is never claimed: not set up yet says so, and reported is the word", async ({
  page,
}) => {
  const { sheet } = await serve(page);

  await expect(row(page, "Review slices")).toContainText(
    "Evidence: not set up yet",
  );
  await sheet.getByRole("tab", { name: "Evidence" }).click();
  await expect(sheet.getByTestId("evidence-not-set-up")).toContainText(
    "observed",
  );
  await expect(sheet.getByTestId("evidence-not-set-up")).toContainText(
    "reported",
  );
  await expect(sheet).not.toContainText(/claimed/i);
});

test("ticking a task done is the user's edit, sent with its version", async ({
  page,
}) => {
  const { writes } = await serve(page);

  await page
    .getByRole("checkbox", { name: "Mark Review slices 1 and 2 as done" })
    .click();

  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0]!.method).toBe("PATCH");
  expect(writes[0]!.url).toContain("/api/ledger/tasks/t3");
  expect(writes[0]!.body).toEqual({ version: 3, status: "done" });
});

test("a task is added from the box", async ({ page }) => {
  const { writes } = await serve(page);

  await page.getByTestId("add-task").fill("Write the release notes");
  await page.getByTestId("add-task").press("Enter");

  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0]!.url).toContain("/api/ledger/projects/p1/tasks");
  expect(writes[0]!.body).toEqual({ title: "Write the release notes" });
});

test("project views are a real tablist; decisions and chats show the ledger's", async ({
  page,
}) => {
  const { sheet } = await serve(page);

  const tasksTab = sheet.getByRole("tab", { name: "Tasks" });
  await tasksTab.focus();
  await page.keyboard.press("ArrowRight");
  await expect(sheet.getByRole("tab", { name: "Evidence" })).toBeFocused();
  await sheet.getByRole("tab", { name: "Decisions" }).click();
  await expect(sheet).toContainText("Ship the ledger before evidence");
});

test("another project and all open tasks open inside the panel", async ({
  page,
}) => {
  const { sheet } = await serve(page);

  await sheet.getByRole("button", { name: /HackMIT/ }).click();
  await expect(
    sheet.getByRole("heading", { name: "HackMIT 2026 judging" }),
  ).toBeVisible();
  await expect(sheet).toContainText("No goal yet · 0 of 1 task done");

  await sheet.getByRole("button", { name: /All open tasks/ }).click();
  const all = sheet.getByTestId("all-open-tasks");
  await expect(all).toContainText("Score the finalists");
  await expect(all).toContainText("Codex adapter for the session watcher");
  await expect(all).not.toContainText("Phase 2.6 polish");
  await expect(page.getByTestId("panel-sheet")).toBeVisible();
});

test("a project keeps its own page link", async ({ page }) => {
  const { sheet } = await serve(page);
  await expect(
    sheet.getByRole("link", { name: "Open OmniHarness as a page" }),
  ).toHaveAttribute("href", "/workspace/projects/p1");
});

test("a new project is created and opened inside the panel", async ({
  page,
}) => {
  const { sheet, writes } = await serve(page);

  await sheet.getByRole("button", { name: "New project" }).click();
  await page
    .getByRole("dialog", { name: "New project" })
    .getByRole("textbox")
    .first()
    .fill("New one");
  await page
    .getByRole("dialog", { name: "New project" })
    .getByRole("button", { name: /Create/ })
    .click();

  await expect.poll(() => writes.length).toBe(1);
  await expect(page.getByTestId("panel-sheet")).toBeVisible();
  await expect(sheet.getByRole("heading", { name: "New one" })).toBeVisible();
});
