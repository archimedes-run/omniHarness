import { expect, test, type Page } from "@playwright/test";

/**
 * MCP Suite > Build (Feature 006 board "MCP-Suite"), given gateway answers.
 * The flow itself is the e2e spec's (tests/e2e/mcp-build.spec.ts); the
 * gateway's states are pytest's (tests/apps/test_mcp_build_flow.py).
 */
const now = new Date().toISOString();
const built = (id: string, state: string, label: string, extra = {}) => ({
  id,
  name: id,
  language: "python",
  description: "Check Devpost submissions and their judging status.",
  status: "verified",
  phase: "verified",
  approved: false,
  detected_secrets: [],
  created_at: now,
  updated_at: now,
  state,
  state_label: label,
  state_reason: null,
  steps: [],
  tool_count: 3,
  tests_passed: null,
  tests_total: null,
  thread_id: null,
  ...extra,
});

async function serve(page: Page, servers: unknown[] | null, status = 200) {
  await page.route("**/api/tool-sources*", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        thread_id: null,
        failing: 0,
        connectors_available: false,
        sources: [],
      }),
    }),
  );
  await page.route("**/api/mcp-studio/servers", (route) =>
    route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify(
        servers
          ? { servers, total: servers.length }
          : { detail: "MCP builder is not enabled" },
      ),
    }),
  );
  await page.goto("/workspace/connections?tab=build");
}

test("Build matches the board: describe box, three steps, list and detail", async ({
  page,
}) => {
  await serve(page, [
    built("hackmit-devpost", "awaiting_approval", "Waiting for your approval", {
      steps: [
        { status: "done", text: "Tests passed in sandbox: 5 of 5" },
        { status: "waiting", text: "First real run needs your approval" },
      ],
    }),
    built("gym-log", "enabled", "Enabled", { approved: true }),
  ]);
  await expect(page.getByRole("tab", { name: "Build" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await expect(
    page.getByRole("heading", { name: "Need a tool that doesn't exist yet?" }),
  ).toBeVisible();
  await expect(
    page.getByRole("textbox", { name: "Describe the tool" }),
  ).toBeVisible();
  for (const step of [
    "You describe it",
    "An agent builds and tests it",
    "You approve its first run",
  ]) {
    await expect(page.getByText(step, { exact: true })).toBeVisible();
  }
  const list = page.getByRole("navigation", { name: "Built servers" });
  await expect(list.getByTestId("built-server")).toHaveCount(2);
  await expect(list.getByTestId("built-server").first()).toContainText(
    "Needs approval",
  );
  await expect(list.getByTestId("built-server").nth(1)).toContainText("Live");
  const detail = page.getByTestId("built-detail");
  await expect(detail.getByTestId("build-state")).toHaveText(
    "Waiting for your approval",
  );
  await expect(
    detail.getByRole("button", { name: "Approve and turn on" }),
  ).toBeVisible();
  // A step's status is said in words to a screen reader, not only by its mark.
  await expect(detail.locator('[data-status="waiting"]')).toContainText(
    "Waiting:",
  );

  await list.getByTestId("built-server").nth(1).click();
  await expect(detail.getByTestId("build-state")).toHaveText("Enabled");
  await expect(
    detail.getByRole("button", { name: "Approve and turn on" }),
  ).toHaveCount(0);
});

test("a failed build says why, and offers no approval", async ({ page }) => {
  await serve(page, [
    built("status-page-watch", "tests_failed", "Tests failed", {
      state_reason: "The server started, but no tools were found.",
    }),
  ]);
  const detail = page.getByTestId("built-detail");
  await expect(detail.getByTestId("build-state")).toHaveText("Tests failed");
  await expect(detail.getByTestId("build-reason")).toHaveText(
    "The server started, but no tools were found.",
  );
  await expect(
    detail.getByRole("button", { name: "Approve and turn on" }),
  ).toHaveCount(0);
});

test("the builder switched off is said, not shown as nothing built", async ({
  page,
}) => {
  await serve(page, null, 503);
  await expect(page.getByTestId("built-unreadable")).toContainText(
    "The MCP builder is off on this gateway",
  );
  await expect(page.getByTestId("built-empty")).toHaveCount(0);
});
