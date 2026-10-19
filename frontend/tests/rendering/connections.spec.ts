import { expect, test, type Page } from "@playwright/test";

/**
 * T090a-d, asserted against what renders (FR-040, FR-041, SC-024).
 *
 * NO BACKEND: the page is served with auth disabled and /api/tool-sources is
 * intercepted, so this asserts the UI given a server response. The server's
 * states — over a real MCP load, including a dead port — are pytest's
 * (tests/test_tool_sources.py).
 */

const VIEW = {
  thread_id: null,
  connectors_available: true,
  failing: 1,
  sources: [
    {
      id: "local:session-watcher",
      name: "session-watcher",
      kind: "local",
      state: "live",
      tool_count: 2,
      error: null,
      selected: null,
    },
    {
      id: "local:dead-server",
      name: "dead-server",
      kind: "local",
      state: "unreachable",
      tool_count: null,
      error: "ConnectError: All connection attempts failed",
      selected: null,
    },
    {
      id: "local:github",
      name: "github",
      kind: "local",
      state: "not-configured",
      tool_count: null,
      error: null,
      selected: null,
    },
    {
      id: "local:filesystem",
      name: "filesystem",
      kind: "local",
      state: "disabled",
      tool_count: null,
      error: null,
      selected: null,
    },
    {
      id: "connector:GMAIL",
      name: "Gmail",
      kind: "connector",
      state: "authorised-not-selected",
      tool_count: null,
      error: null,
      selected: false,
    },
    {
      id: "connector:SLACK",
      name: "Slack",
      kind: "connector",
      state: "not-authorised",
      tool_count: null,
      error: null,
      selected: false,
    },
  ],
};

/** The servers that have an entry in extensions_config, so can be toggled. */
const MCP_CONFIG = {
  mcp_servers: {
    "dead-server": { enabled: true, type: "sse", url: "http://x/sse" },
    "session-watcher": { enabled: true, type: "sse", url: "http://y/sse" },
  },
};

async function serve(page: Page, body: Record<string, unknown>) {
  const puts: unknown[] = [];
  await page.route("**/api/tool-sources*", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(body),
    }),
  );
  await page.route("**/api/mcp/config", (route) => {
    if (route.request().method() === "PUT") {
      puts.push(route.request().postDataJSON());
    }
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(MCP_CONFIG),
    });
  });
  // Phase 2.5: tool sources moved to Settings → Connections.
  await page.goto("/workspace/settings/connections");
  return puts;
}

const row = (page: Page, id: string) =>
  page.locator(`[data-testid="tool-source"][data-source="${id}"]`);

test("an unreachable source does not look like one nobody configured (FR-040)", async ({
  page,
}) => {
  await serve(page, VIEW);

  const dead = row(page, "local:dead-server");
  const absent = row(page, "local:github");
  await expect(dead).toHaveAttribute("data-state", "unreachable");
  await expect(absent).toHaveAttribute("data-state", "not-configured");
  await expect(dead).toContainText("Unreachable");
  await expect(absent).toContainText("Not configured");
  // The reason is on the failing source, and only there.
  await expect(dead.getByTestId("source-error")).toContainText(
    "All connection attempts failed",
  );
  await expect(absent.getByTestId("source-error")).toHaveCount(0);
});

test("a load failure reaches the user, on the page and in the sidebar (FR-041)", async ({
  page,
}) => {
  await serve(page, VIEW);

  await expect(page.getByTestId("failing")).toContainText(
    "1 tool source is failing",
  );
  await expect(page.getByTestId("failing-sources")).toHaveText("1");
});

test("an authorised connector reads Live, not unauthorised (SC-024), and offers the right action", async ({
  page,
}) => {
  await serve(page, {
    ...VIEW,
    sources: VIEW.sources.map((s) =>
      s.id === "connector:GMAIL"
        ? { ...s, state: "authorised", selected: null }
        : s,
    ),
  });

  await expect(row(page, "connector:GMAIL")).toContainText("Live");
  await expect(
    row(page, "connector:GMAIL").getByRole("button", { name: "Disconnect" }),
  ).toBeVisible();
  await expect(row(page, "connector:SLACK")).toContainText("Not configured");
  await expect(
    row(page, "connector:SLACK").getByRole("button", { name: "Connect" }),
  ).toBeVisible();
});

test("turning a server off writes enabled: false for that server, and only that server", async ({
  page,
}) => {
  const puts = await serve(page, VIEW);

  await row(page, "local:dead-server")
    .getByRole("button", { name: "Turn off" })
    .click();

  await expect.poll(() => puts.length).toBe(1);
  const sent = puts[0] as { mcp_servers: Record<string, { enabled: boolean }> };
  expect(sent.mcp_servers["dead-server"]!.enabled).toBe(false);
  expect(sent.mcp_servers["session-watcher"]!.enabled).toBe(true);
});

test("nothing failing shows no alarm", async ({ page }) => {
  await serve(page, {
    ...VIEW,
    failing: 0,
    sources: VIEW.sources.filter((s) => s.state !== "unreachable"),
  });

  await expect(page.getByTestId("failing")).toHaveCount(0);
  await expect(page.getByTestId("failing-sources")).toHaveCount(0);
});
