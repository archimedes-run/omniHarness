import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

/**
 * MCP Suite > Build, end to end against a fake gateway that keeps state:
 * describe a tool -> drafting -> tests pass in the sandbox -> waiting for your
 * approval -> the user approves -> enabled. The promise under test: nothing
 * turns the server on until the user approves, and the key typed into the
 * description comes back only as its placeholder.
 */
const SECRET = "dv_9f8e7d6c5b4a1234zz";

type Server = Record<string, unknown> & { id: string; state: string };

function gateway(page: Page) {
  const calls: string[] = [];
  let server: Server | null = null;
  const now = new Date().toISOString();
  const json = (body: unknown, status = 200) => ({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
  void page.route("**/api/tool-sources*", (route) =>
    route.fulfill(
      json({
        thread_id: null,
        failing: 0,
        connectors_available: false,
        sources: [],
      }),
    ),
  );
  void page.route("**/api/mcp-studio/builds", async (route) => {
    calls.push("build");
    const { description } = route.request().postDataJSON() as {
      description: string;
    };
    server = {
      id: "srv-1",
      name: "check-devpost-submissions",
      language: "python",
      // What the real gateway stores: the value lifted out.
      description: description.replace(SECRET, "{{secret:TOKEN}}"),
      status: "not_running",
      phase: "idle",
      approved: false,
      detected_secrets: [],
      created_at: now,
      updated_at: now,
      state: "drafting",
      state_label: "Drafting",
      state_reason: null,
      steps: [{ status: "waiting", text: "The agent is writing the server" }],
      tool_count: null,
      tests_passed: null,
      tests_total: null,
      thread_id: "t-build",
    };
    await route.fulfill(
      json(
        {
          server_id: "srv-1",
          thread_id: "t-build",
          name: server.name,
          secret_placeholders: ["TOKEN"],
        },
        201,
      ),
    );
  });
  void page.route("**/api/mcp-studio/servers/srv-1/enable", async (route) => {
    calls.push("enable");
    if (server?.state !== "awaiting_approval") {
      return route.fulfill(json({ detail: "not yet" }, 409));
    }
    server = {
      ...server,
      approved: true,
      status: "deployed",
      state: "enabled",
      state_label: "Enabled",
      steps: [
        ...(server.steps as unknown[]).slice(0, -1),
        { status: "done", text: "You approved its first run" },
        { status: "done", text: "On: agents can use its tools" },
      ],
    };
    return route.fulfill(json(server));
  });
  void page.route("**/api/mcp-studio/servers", (route) =>
    route.fulfill(
      json({ servers: server ? [server] : [], total: server ? 1 : 0 }),
    ),
  );
  /** The sandbox tests passed: what the gateway reports next. */
  const testsPassed = () => {
    server = {
      ...server!,
      status: "verified",
      phase: "verified",
      state: "awaiting_approval",
      state_label: "Waiting for your approval",
      tool_count: 1,
      tests_passed: 1,
      tests_total: 1,
      detected_secrets: ["TOKEN"],
      steps: [
        { status: "done", text: "Scaffolded server, 1 tool: whoami" },
        { status: "done", text: "Tests passed in sandbox: 1 of 1" },
        {
          status: "done",
          text: "Uses secret TOKEN: stored, never shown to the model",
        },
        { status: "waiting", text: "First real run needs your approval" },
      ],
    };
  };
  return { calls, testsPassed, state: () => server?.state };
}

test("describe -> build in the sandbox -> approval required before it is enabled", async ({
  page,
}) => {
  mockLangGraphAPI(page);
  const gw = gateway(page);
  await page.goto("/workspace/connections?tab=build");

  await page
    .getByRole("textbox", { name: "Describe the tool" })
    .fill(`check my Devpost submissions, my token is ${SECRET}`);
  await page.getByRole("button", { name: "Build it" }).click();

  const detail = page.getByTestId("built-detail");
  await expect(detail.getByTestId("build-state")).toHaveText("Drafting", {
    timeout: 15_000,
  });
  await expect(page.getByTestId("secrets-hidden")).toContainText(
    "{{secret:TOKEN}}",
  );
  // The key never comes back to the page.
  expect(await page.content()).not.toContain(SECRET);
  // Drafting: nothing to approve, nothing turned on.
  await expect(
    page.getByRole("button", { name: "Approve and turn on" }),
  ).toHaveCount(0);

  // The sandbox tests pass; the page polls and asks for approval.
  gw.testsPassed();
  await expect(detail.getByTestId("build-state")).toHaveText(
    "Waiting for your approval",
    { timeout: 15_000 },
  );
  await expect(detail).toContainText("Tests passed in sandbox: 1 of 1");
  await expect(detail).toContainText("First real run needs your approval");
  // Still not enabled, and nothing asked the gateway to enable it.
  expect(gw.calls).toEqual(["build"]);
  expect(gw.state()).toBe("awaiting_approval");

  await page.getByRole("button", { name: "Approve and turn on" }).click();
  await expect(detail.getByTestId("build-state")).toHaveText("Enabled");
  expect(gw.calls).toEqual(["build", "enable"]);
  await expect(detail).toContainText("On: agents can use its tools");
});
