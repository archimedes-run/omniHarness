import { expect, test } from "@playwright/test";

/**
 * Phase 2.5 — the workflow list takes each workflow's newest run from the list
 * response. It used to fetch every run of every workflow: one request per
 * workflow (16 on a real page).
 */
test("the workflow list makes no per-workflow runs request", async ({
  page,
}) => {
  const json = (body: unknown) => ({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
  const workflow = (n: number) => ({
    id: `wf-${n}`,
    owner_id: "u1",
    title: `Workflow ${n}`,
    description: null,
    status: "active",
    current_version_id: null,
    created_at: "2026-10-19T12:00:00Z",
    updated_at: "2026-10-19T12:00:00Z",
    last_run:
      n === 1
        ? {
            id: "run-1",
            workflow_id: "wf-1",
            status: "succeeded",
            trigger_type: "manual",
            created_at: "2026-10-19T12:05:00Z",
            updated_at: "2026-10-19T12:06:00Z",
          }
        : null,
  });
  let runRequests = 0;
  await page.route("**/api/workflows/*/runs", (route) => {
    runRequests += 1;
    return route.fulfill(json([]));
  });
  await page.route("**/api/workflows/templates", (route) =>
    route.fulfill(json([])),
  );
  await page.route("**/api/workflows", (route) =>
    route.fulfill(json([1, 2, 3].map(workflow))),
  );
  // Phase 2.5: workflows are listed on Automations.
  await page.goto("/workspace/automations");

  await expect(page.getByText("Workflow 3")).toBeVisible();
  await page.waitForTimeout(500);
  expect(runRequests).toBe(0);
});
