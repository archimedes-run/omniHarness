import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

/**
 * Feature 006 "+" picker, end to end: "Connect" on an app that is not
 * connected opens Composio's sign-in in a pop-up (the same flow as MCP Suite),
 * and when sign-in completes the row reads "Connected" and can be switched on
 * for this chat. A blocked pop-up, a cancel and a failure each say so.
 *
 * window.open is replaced by a recorder (no real window, no real Composio),
 * and the gateway is a small stateful fake: once the connection is "active",
 * the live view reports Slack as authorised.
 */

const json = (body: unknown, status = 200) => ({
  status,
  contentType: "application/json",
  body: JSON.stringify(body),
});

interface Fake {
  /** Status the gateway reports for SLACK. */
  status: "pending" | "active" | "failed";
  initiated: number;
  puts: string[][];
}

function mockGateway(page: Page): Fake {
  const fake: Fake = { status: "pending", initiated: 0, puts: [] };
  let sources: string[] = [];
  const item = (slug: string, name: string) => ({
    tool_id: `connector:${slug}`,
    name,
    description: "",
    source: "connector",
    origin: "builtin",
    toolkit: slug,
    icon: null,
    category: "",
    connected: false,
    pinned: false,
  });
  void page.route("**/api/tools/catalog", (route) =>
    route.fulfill(json({ categories: [], items: [item("SLACK", "Slack")] })),
  );
  void page.route("**/api/threads/*/tools/count", (route) =>
    route.fulfill(json({ count: 3, cap: 40, over_cap: false })),
  );
  void page.route("**/api/threads/*/tools", (route) => {
    if (route.request().method() === "PUT") {
      sources = (route.request().postDataJSON() as { sources: string[] })
        .sources;
      fake.puts.push(sources);
    }
    return route.fulfill(json({ thread_id: "t", sources, pinned: [] }));
  });
  void page.route("**/api/tool-sources*", (route) =>
    route.fulfill(
      json({
        thread_id: null,
        failing: 0,
        connectors_available: true,
        sources: [
          {
            id: "connector:SLACK",
            name: "Slack",
            kind: "connector",
            state:
              fake.status === "active"
                ? "authorised-not-selected"
                : "not-authorised",
            tool_count: null,
            error: null,
            selected: null,
          },
        ],
      }),
    ),
  );
  void page.route("**/api/threads/*/skills", (route) =>
    route.fulfill(json({ thread_id: "t", excluded: [] })),
  );
  void page.route("**/api/composio/connections/initiate", (route) => {
    fake.initiated++;
    return route.fulfill(
      json({
        composio_redirect_url: "https://connect.composio.dev/link/fake",
        connection_id: "conn-1",
      }),
    );
  });
  void page.route("**/api/composio/connections/SLACK", (route) =>
    route.fulfill(
      json({ status: fake.status, toolkit: "SLACK", account_display: null }),
    ),
  );
  return fake;
}

/** Replace window.open: record each call; null when `blocked`. */
async function recordPopups(page: Page, blocked = false) {
  await page.addInitScript((isBlocked) => {
    const w = window as unknown as {
      __popups: { url: string; name: string; hrefs: string[] }[];
    };
    w.__popups = [];
    window.open = (url?: string | URL, name?: string): Window | null => {
      if (isBlocked) return null;
      const entry: { url: string; name: string; hrefs: string[] } = {
        url: String(url ?? ""),
        name: name ?? "",
        hrefs: [],
      };
      w.__popups.push(entry);
      const location = {
        set href(v: string) {
          entry.hrefs.push(v);
        },
        get href() {
          return entry.hrefs.at(-1) ?? "about:blank";
        },
      };
      return {
        closed: false,
        close() {
          (this as { closed: boolean }).closed = true;
        },
        location,
      } as unknown as Window;
    };
  }, blocked);
}

const popups = (page: Page) =>
  page.evaluate(
    () =>
      (window as unknown as { __popups: { name: string; hrefs: string[] }[] })
        .__popups,
  );

async function openIntegrations(page: Page) {
  await page.goto("/workspace/chats/new");
  const add = page.getByRole("button", { name: "Add context" });
  await expect(add).toBeVisible({ timeout: 15_000 });
  await add.click();
  const picker = page.getByRole("dialog", { name: "Add context" });
  await picker.getByRole("tab", { name: "Integrations" }).click();
  const slack = picker.getByRole("listitem").filter({ hasText: "Slack" });
  await expect(slack.getByTestId("integration-status")).toHaveText(
    "Not connected",
  );
  return { picker, slack };
}

test("Connect opens the sign-in pop-up; on completion the row is Connected and can be switched on", async ({
  page,
}) => {
  mockLangGraphAPI(page);
  const fake = mockGateway(page);
  await recordPopups(page);
  const { slack } = await openIntegrations(page);

  // Not a link to MCP Suite any more: a button that signs in right here.
  await expect(slack.getByRole("link")).toHaveCount(0);
  await slack.getByRole("button", { name: "Connect Slack" }).click();

  await expect(slack.getByTestId("connect-message")).toHaveText(
    /Waiting for sign-in/,
  );
  expect(fake.initiated).toBe(1);
  const opened = await popups(page);
  expect(opened).toHaveLength(1);
  expect(opened[0]!.name).toBe("composio_oauth");
  expect(opened[0]!.hrefs).toEqual(["https://connect.composio.dev/link/fake"]);
  await expect(slack.getByRole("switch")).toHaveCount(0);

  // The callback page in the pop-up reports success to its opener.
  fake.status = "active";
  await page.evaluate(() =>
    window.postMessage(
      { type: "composio_connected", toolkit: "SLACK" },
      window.location.origin,
    ),
  );

  await expect(slack.getByTestId("integration-status")).toHaveText("Connected");
  const toggle = slack.getByRole("switch", { name: "Use Slack in this chat" });
  await expect(toggle).not.toBeChecked();
  await toggle.click();
  await expect.poll(() => fake.puts.at(-1)).toEqual(["connector:SLACK"]);
  await expect(toggle).toBeChecked();
});

test("a blocked pop-up says so, and nothing is started", async ({ page }) => {
  mockLangGraphAPI(page);
  const fake = mockGateway(page);
  await recordPopups(page, true);
  const { slack } = await openIntegrations(page);
  await slack.getByRole("button", { name: "Connect Slack" }).click();
  await expect(slack.getByTestId("connect-message")).toHaveText(
    /blocked the sign-in pop-up/,
  );
  expect(fake.initiated).toBe(0);
  await expect(
    slack.getByRole("button", { name: "Connect Slack" }),
  ).toBeEnabled();
});

test("cancelling while the pop-up is open says so", async ({ page }) => {
  mockLangGraphAPI(page);
  mockGateway(page);
  await recordPopups(page);
  const { slack } = await openIntegrations(page);
  await slack.getByRole("button", { name: "Connect Slack" }).click();
  await slack
    .getByRole("button", { name: "Cancel signing in to Slack" })
    .click();
  await expect(slack.getByTestId("connect-message")).toHaveText(
    "Sign-in cancelled. Nothing was connected.",
  );
  await expect(slack.getByTestId("integration-status")).toHaveText(
    "Not connected",
  );
});

test("a failed sign-in says so", async ({ page }) => {
  mockLangGraphAPI(page);
  const fake = mockGateway(page);
  await recordPopups(page);
  const { slack } = await openIntegrations(page);
  await slack.getByRole("button", { name: "Connect Slack" }).click();
  await expect(slack.getByTestId("connect-message")).toHaveText(
    /Waiting for sign-in/,
  );
  fake.status = "failed";
  await expect(slack.getByTestId("connect-message")).toHaveText(
    "Sign-in failed. Nothing was connected.",
    { timeout: 10_000 },
  );
  await expect(slack.getByTestId("integration-status")).toHaveText(
    "Not connected",
  );
});
