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

async function serve(
  page: Page,
  body: Record<string, unknown>,
  retried: Record<string, unknown> = body,
) {
  const puts: unknown[] = [];
  const retries: string[] = [];
  await page.route("**/api/tool-sources/retry", (route) => {
    retries.push(route.request().method());
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(retried),
    });
  });
  await page.route("**/api/tool-sources", (route) =>
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
  await page.route("**/api/composio/catalog", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        toolkits: [
          {
            slug: "gmail",
            name: "Gmail",
            icon: "",
            category: "Communication",
            description: "Read, search and draft email",
            status: "connected",
            account_display: null,
          },
          {
            slug: "slack",
            name: "Slack",
            icon: "",
            category: "Communication",
            description: "Channels and messages",
            status: "not_connected",
            account_display: null,
          },
        ],
      }),
    }),
  );
  // Feature 006: the sidebar's MCP Suite item is this page.
  await page.goto("/workspace/connections");
  return { puts, retries };
}

const row = (page: Page, id: string) =>
  page.locator(`[data-testid="tool-source"][data-source="${id}"]`);
const attention = (page: Page, id: string) =>
  page.locator(`[data-testid="needs-attention"][data-source="${id}"]`);

test("Connected matches the board: title, a real tablist, counts", async ({
  page,
}) => {
  await serve(page, VIEW);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("MCP Suite");
  const h1 = await page
    .getByRole("heading", { level: 1 })
    .evaluate((el) => getComputedStyle(el).fontSize);
  expect(h1).toBe("24px");
  const tabs = page.getByRole("tablist", { name: "MCP Suite views" });
  await expect(tabs.getByRole("tab")).toHaveText(["Connected", "Build"]);
  await expect(tabs.getByRole("tab", { name: "Connected" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  // live: session-watcher + Gmail; unreachable: dead-server; not connected:
  // github (no entry) + Slack; off: filesystem.
  await expect(page.getByTestId("count-live")).toHaveText("2 live");
  await expect(page.getByTestId("count-unreachable")).toHaveText(
    "1 unreachable",
  );
  await expect(page.getByTestId("count-not-connected")).toHaveText(
    "2 not connected",
  );
  await expect(page.getByTestId("count-off")).toHaveText("1 off");
  // One solid primary button on the screen: Browse apps.
  await expect(page.getByRole("button", { name: "Browse apps" })).toBeVisible();
});

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
  // The failing source is called out on its own, with its REAL error.
  await expect(
    attention(page, "local:dead-server").getByTestId("source-error"),
  ).toHaveText("ConnectError: All connection attempts failed");
  await expect(attention(page, "local:github")).toHaveCount(0);
});

test("a load failure reaches the user, on the page and in the sidebar (FR-041)", async ({
  page,
}) => {
  await serve(page, VIEW);

  await expect(page.getByTestId("needs-attention")).toHaveCount(1);
  await expect(attention(page, "local:dead-server")).toContainText(
    "dead-server can't be reached",
  );
  await expect(page.getByTestId("failing-sources")).toHaveText("1");
});

test("Retry loads again and shows what the load observed", async ({ page }) => {
  const fixed = {
    ...VIEW,
    failing: 0,
    sources: VIEW.sources.map((s) =>
      s.id === "local:dead-server"
        ? { ...s, state: "live", tool_count: 3, error: null }
        : s,
    ),
  };
  const { retries } = await serve(page, VIEW, fixed);
  await attention(page, "local:dead-server")
    .getByRole("button", { name: "Retry" })
    .click();
  await expect.poll(() => retries).toEqual(["POST"]);
  await expect(page.getByTestId("needs-attention")).toHaveCount(0);
  await expect(row(page, "local:dead-server")).toContainText("Live");
  await expect(row(page, "local:dead-server")).toContainText("3 tools");
});

test("apps are cards with their official logo; connected ones read Live and disconnect from their menu", async ({
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

  const gmail = row(page, "connector:GMAIL");
  await expect(gmail.getByRole("img", { name: "Gmail logo" })).toBeVisible();
  await expect(gmail).toContainText("Read, search and draft email");
  await expect(gmail).toContainText("Live");
  await gmail.getByRole("button", { name: "Gmail options" }).click();
  await expect(
    page.getByRole("menuitem", { name: "Disconnect Gmail" }),
  ).toBeVisible();
  await page.keyboard.press("Escape");

  const slack = row(page, "connector:SLACK");
  await expect(slack.getByRole("img", { name: "Slack logo" })).toBeVisible();
  await expect(slack.getByRole("button", { name: "Connect" })).toBeVisible();
});

test("turning a server off writes enabled: false for that server, and only that server", async ({
  page,
}) => {
  const { puts } = await serve(page, VIEW);

  await row(page, "local:dead-server")
    .getByRole("switch", { name: "Turn off dead-server" })
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

  await expect(page.getByTestId("count-live")).toBeVisible();
  await expect(page.getByTestId("needs-attention")).toHaveCount(0);
  await expect(page.getByTestId("count-unreachable")).toHaveCount(0);
  await expect(page.getByTestId("failing-sources")).toHaveCount(0);
});

test("unreadable sources say can't tell, never none", async ({ page }) => {
  await page.route("**/api/tool-sources", (route) =>
    route.fulfill({ status: 500, body: "boom" }),
  );
  await page.goto("/workspace/connections");
  await expect(page.getByTestId("unreadable")).toContainText(
    "can't tell which tool sources are working",
  );
  await expect(page.getByTestId("count-live")).toHaveCount(0);
});
