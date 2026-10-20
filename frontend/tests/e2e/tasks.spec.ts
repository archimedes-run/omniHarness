import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

/**
 * Feature 006, Tasks panel, end to end through the capsule against a small
 * stateful fake of the ledger: a task added in the panel appears in To do;
 * ticking it moves it to Done this week, sent with the version it was read at
 * (a stale version is refused with 409, as the ledger refuses it).
 */
type Task = {
  id: string;
  project_id: string;
  short_id: string;
  title: string;
  status: string;
  owner: null;
  due_date: null;
  goal_id: null;
  version: number;
  done_at: string | null;
};

function fakeLedger(page: Page) {
  const now = new Date().toISOString();
  const project = {
    id: "p1",
    name: "Beta launch",
    why: null,
    status: "active",
    context: null,
    version: 1,
    created_at: now,
    updated_at: now,
  };
  const state = { tasks: [] as Task[], writes: [] as string[] };
  const json = (body: unknown, status = 200) => ({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
  const open = () => state.tasks.filter((t) => t.status !== "done").length;
  void page.route("**/api/ledger/projects", (route) =>
    route.fulfill(
      json([{ ...project, open_tasks: open(), overdue: 0, done_tasks: 0 }]),
    ),
  );
  void page.route("**/api/ledger/projects/p1", (route) =>
    route.fulfill(
      json({ project, goals: [], tasks: state.tasks, notes: [], links: [] }),
    ),
  );
  void page.route("**/api/ledger/projects/p1/tasks", (route) => {
    const body = route.request().postDataJSON() as { title: string };
    state.writes.push("create");
    const task: Task = {
      id: `t${state.tasks.length + 1}`,
      project_id: "p1",
      short_id: `T-${state.tasks.length + 1}`,
      title: body.title,
      status: "todo",
      owner: null,
      due_date: null,
      goal_id: null,
      version: 1,
      done_at: null,
    };
    state.tasks.push(task);
    return route.fulfill(json(task, 201));
  });
  void page.route("**/api/ledger/tasks/*", (route) => {
    const id = route.request().url().split("/").pop()!;
    const body = route.request().postDataJSON() as {
      version: number;
      status: string;
    };
    const task = state.tasks.find((t) => t.id === id)!;
    state.writes.push(`patch:${body.version}`);
    if (body.version !== task.version)
      return route.fulfill(json({ detail: "stale" }, 409));
    task.status = body.status;
    task.version += 1;
    task.done_at = body.status === "done" ? new Date().toISOString() : null;
    return route.fulfill(json(task));
  });
  return state;
}

test("a task added in the Tasks panel appears, and ticking it marks it done", async ({
  page,
}) => {
  mockLangGraphAPI(page);
  const ledger = fakeLedger(page);
  await page.goto("/workspace/chats/new");
  const capsule = page.locator(
    "[data-testid='capsule'] [data-capsule='tasks']",
  );
  await expect(capsule).toBeVisible({ timeout: 15_000 });
  await capsule.click();
  const sheet = page.getByTestId("panel-sheet");
  await expect(sheet.getByTestId("no-tasks")).toBeVisible();

  await sheet.getByTestId("add-task").fill("Write the launch post");
  await sheet.getByTestId("add-task").press("Enter");

  const todo = sheet.getByTestId("group-todo");
  await expect(todo).toContainText("Write the launch post");
  await expect(
    sheet.getByRole("button", { name: /Beta launch/ }),
  ).toContainText("1");

  await sheet
    .getByRole("checkbox", { name: "Mark Write the launch post as done" })
    .click();
  await expect(sheet.getByTestId("group-done")).toContainText(
    "Write the launch post",
  );
  expect(ledger.writes).toEqual(["create", "patch:1"]);
});
