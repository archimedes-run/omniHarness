import { expect, test, type Page } from "@playwright/test";

/**
 * The sidebar (Feature 006): New chat · Chats · MCP Suite, a divider, Recent
 * chats; the user and More (Settings, Memory, Safety, Activity log,
 * Appearance, About) in the footer. Agents, Automations, Projects and Inbox
 * left it: the first three are capsule panels, Inbox is Home.
 *
 * New chat carries what is waiting on you (confirmations + alerts), "?" when
 * that cannot be read; MCP Suite carries the failing-source count (Feature
 * 004 FR-041); a dot on More says something inside it needs attention.
 */
const json = (body: unknown) => ({
  status: 200,
  contentType: "application/json",
  body: JSON.stringify(body),
});

const POLICY = (keptPrevious: boolean) => ({
  source_file: "rules.yaml",
  rules: [],
  unreadable: false,
  kept_previous: keptPrevious,
  error: keptPrevious ? "line 4: not a list" : null,
  threshold_targets: 10,
  expires_after_seconds: 14400,
});

async function serve(
  page: Page,
  {
    failing = 0,
    keptPrevious = false,
    pending = 0,
    alertsWaiting = 0,
    confirmationsReadable = true,
  } = {},
) {
  await page.route("**/api/tool-sources*", (route) =>
    route.fulfill(
      json({
        thread_id: null,
        failing,
        connectors_available: false,
        sources: [],
      }),
    ),
  );
  await page.route("**/api/policy/rules", (route) =>
    route.fulfill(json(POLICY(keptPrevious))),
  );
  await page.route("**/api/confirmations", (route) =>
    route.fulfill(
      json({
        actions: Array.from({ length: pending }, (_, i) => ({
          id: `a${i}`,
          tool_name: "calendar_decline",
          plan_text: "I will decline 1 meeting",
          targets: ["Standup"],
          requester: "lead_agent",
          delegation_chain: [],
          expires_at: new Date(Date.now() + 3_600_000).toISOString(),
          thread_id: "t1",
          threshold_targets: 10,
          requires_typed_count: false,
          withheld: false,
        })),
        readable: confirmationsReadable,
        error: confirmationsReadable ? "" : "store unreadable",
      }),
    ),
  );
  await page.route("**/api/inbox/alerts", (route) =>
    route.fulfill(json({ alerts: [], waiting_count: alertsWaiting })),
  );
  await page.route("**/threads/search", (route) =>
    route.fulfill(
      json([
        {
          thread_id: "th1",
          updated_at: new Date().toISOString(),
          values: { title: "Launch day plan" },
          metadata: {},
        },
      ]),
    ),
  );
  await page.goto("/workspace/chats");
}

test("the sidebar reads New chat, Chats, MCP Suite, then Recent chats", async ({
  page,
}) => {
  await serve(page);
  const sidebar = page.locator('[data-sidebar="sidebar"]');
  await expect(sidebar.getByText("Recent chats")).toBeVisible();
  const labels = (
    await sidebar
      .locator('[data-sidebar="group"]')
      .first()
      .locator('[data-sidebar="menu-button"]')
      .allInnerTexts()
  ).map((l) => l.trim());
  expect(labels).toEqual(["New chat", "Chats", "MCP Suite"]);
  // The nav comes before the divider, Recent chats after it.
  const order = await sidebar.evaluate((el) => {
    const nav = el.querySelector('a[href="/workspace/connections"]')!;
    const divider = el.querySelector('[data-sidebar="separator"]')!;
    const recent = Array.from(el.querySelectorAll("*")).find(
      (n) => n.textContent === "Recent chats",
    )!;
    const before = (a: Node, b: Node) =>
      Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
    return before(nav, divider) && before(divider, recent);
  });
  expect(order).toBe(true);
  // What left the sidebar.
  for (const gone of [
    "Agents",
    "Automations",
    "Projects",
    "Inbox",
    "Connections",
  ]) {
    await expect(
      sidebar.locator('[data-sidebar="menu-button"]', { hasText: gone }),
      gone,
    ).toHaveCount(0);
  }
  for (const href of [
    "/workspace/agents",
    "/workspace/automations",
    "/workspace/projects",
    "/workspace/inbox",
  ]) {
    await expect(sidebar.locator(`a[href="${href}"]`), href).toHaveCount(0);
  }
});

test("New chat counts what is waiting on you, and links to Home", async ({
  page,
}) => {
  await serve(page, { pending: 1, alertsWaiting: 2 });
  // Main board: New chat is Home (the dashboard with the chat bar under it).
  const newChat = page.locator(
    '[data-sidebar="menu-item"]:has(a[href="/workspace/home"])',
  );
  await expect(newChat.getByRole("link", { name: "New chat" })).toHaveAttribute(
    "href",
    "/workspace/home",
  );
  const badge = newChat.getByTestId("inbox-badge");
  await expect(badge).toHaveText("3");
  await expect(badge).toHaveAttribute("href", "/workspace/home");
  await expect(badge).toHaveAccessibleName("3 things are waiting on you");
});

test("New chat says it cannot tell, rather than 0, when the pending set is unreadable", async ({
  page,
}) => {
  await serve(page, { confirmationsReadable: false });
  const badge = page.getByTestId("inbox-badge");
  await expect(badge).toHaveText("?");
  await expect(badge).toHaveAttribute("data-count", "unknown");
});

test("nothing waiting shows no badge on New chat", async ({ page }) => {
  await serve(page);
  await expect(page.getByText("MCP Suite")).toBeVisible();
  await expect(page.getByTestId("inbox-badge")).toHaveCount(0);
});

test("the footer shows the user's display name and its initials", async ({
  page,
}) => {
  await page.route("**/api/preferences", (route) =>
    route.fulfill(
      json({
        appearance: "light",
        appearance_chosen: false,
        display_name: "Rishabh Sharma",
        display_name_effective: "Rishabh Sharma",
      }),
    ),
  );
  await serve(page);
  await expect(page.getByTestId("sidebar-user-name")).toHaveText(
    "Rishabh Sharma",
  );
  await expect(
    page.getByTestId("sidebar-user").locator('[data-slot="avatar-fallback"]'),
  ).toHaveText("RS");
});

test("with no preferences to read, the footer falls back to the email's name", async ({
  page,
}) => {
  await page.route("**/api/preferences", (route) =>
    route.fulfill({ status: 404, body: "" }),
  );
  await serve(page);
  // OMNI_HARNESS_AUTH_DISABLED serves e2e@test.local.
  await expect(page.getByTestId("sidebar-user-name")).toHaveText("e2e");
  await expect(
    page.getByTestId("sidebar-user").locator('[data-slot="avatar-fallback"]'),
  ).toHaveText("E2");
});

test("More holds Settings, Memory, Safety, Activity log, Appearance and About", async ({
  page,
}) => {
  await serve(page);
  await expect(
    page.locator('[data-sidebar="sidebar"] a[href^="/workspace/settings"]'),
  ).toHaveCount(0);
  await page.getByTestId("more-button").click();
  const items = page.getByRole("menuitem");
  const expected: [string, string][] = [
    ["Settings", "/workspace/settings"],
    ["Memory", "/workspace/settings/memory"],
    ["Safety", "/workspace/settings/safety"],
    ["Activity log", "/workspace/settings/activity"],
    ["Appearance", "/workspace/settings/appearance"],
    ["About", "/workspace/settings/about"],
  ];
  for (const [i, [name, href]] of expected.entries()) {
    await expect(items.nth(i)).toHaveText(name);
    await expect(items.nth(i)).toHaveAttribute("href", href);
  }
  await expect(page.getByTestId("more-settings")).toHaveAttribute(
    "href",
    "/workspace/settings",
  );
});

test("a failing tool source shows on MCP Suite without opening anything (FR-041)", async ({
  page,
}) => {
  await serve(page, { failing: 2 });
  const suite = page.locator(
    '[data-sidebar="menu-item"]:has(a[href="/workspace/connections"])',
  );
  await expect(suite).toContainText("MCP Suite");
  await expect(suite.getByTestId("failing-sources")).toHaveText("2");
  await expect(
    suite.getByRole("img", { name: "2 tool sources failing" }),
  ).toBeVisible();
});

test("More carries a dot when something inside it needs attention, and only then", async ({
  page,
}) => {
  await serve(page, { keptPrevious: false });
  await expect(page.getByTestId("more-attention")).toHaveCount(0);

  await serve(page, { keptPrevious: true });
  await expect(page.getByTestId("more-attention")).toBeVisible();
});
