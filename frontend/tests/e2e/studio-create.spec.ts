import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";
import { studioGateway, type GatewayState } from "./utils/studio-gateway";

/**
 * Agent Studio and Skill Studio, "+ New" from one sentence, end to end
 * (Feature 006, Phase 3), in the capsule's panel over a chat.
 *
 * The e2e suite has no backend, so the gateway is a STATEFUL stand-in with
 * the real routers' response shapes (utils/studio-gateway.ts): versions,
 * stale-write refusals and undo behave as the versioned store does. The
 * chat's members are the thread's state, as in multi-agent-members.spec.ts.
 */
const THREAD = "00000000-0000-0000-0000-0000000000c3";
const SENTENCE =
  "Every weekday at 6pm, tell me what moved on OmniHarness and add tasks for what's stuck";

async function setUp(page: Page) {
  mockLangGraphAPI(page, {
    threads: [{ thread_id: THREAD, title: "Planning" }],
  });
  const members: string[] = [];
  const calls: string[] = [];
  const view = () => ({
    thread_id: THREAD,
    participants: [
      { name: "lead_agent", description: "Leads this chat", lead: true },
      ...members.map((name) => ({ name, description: "", lead: false })),
    ],
  });
  await page.route("**/api/threads/*/participants", (route) => {
    const request = route.request();
    if (request.method() === "POST") {
      const { agent } = request.postDataJSON() as { agent: string };
      calls.push(`POST ${agent}`);
      if (!members.includes(agent)) members.push(agent);
    }
    return route.fulfill({ json: view() });
  });
  await page.route("**/api/inbox/alerts", (route) =>
    route.fulfill({ json: { alerts: [], waiting_count: 0 } }),
  );
  await page.route("**/api/confirmations", (route) =>
    route.fulfill({ json: { actions: [], readable: true, error: "" } }),
  );
  const gateway = await studioGateway(page);
  return { gateway, calls, members };
}

const openPanel = (page: Page, panel: string, item?: string) =>
  page.goto(
    `/workspace/chats/${THREAD}?panel=${panel}${item ? `&item=${item}` : ""}`,
  );

async function draftNewAgent(page: Page) {
  await page.getByTestId("studio-new").click();
  // "+ New agent" opens on Instructions, with the one-sentence bar.
  await expect(page.getByTestId("studio-tab-instructions")).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await page.getByLabel("Describe the agent in one sentence").fill(SENTENCE);
  await page
    .getByTestId("agent-draft-bar")
    .getByRole("button", { name: "Draft" })
    .click();
  await expect(page.getByTestId("draft-note")).toContainText(
    "Every tab is filled in for review",
  );
}

const versionsOf = (gateway: GatewayState, name: string) =>
  gateway.agents.get(name)?.versions ?? [];

test("1. one sentence creates an agent in place, and every tab is filled", async ({
  page,
}) => {
  const { gateway } = await setUp(page);
  await openPanel(page, "agents");
  await draftNewAgent(page);

  // Instructions.
  await expect(page.getByTestId("agent-instructions")).toHaveValue(
    "You are my evening wrap-up.\n1. What moved today.\n2. What is stuck.",
  );
  // Overview: name, one line, Works on, Uses, Next run (suggested only).
  await page.getByTestId("studio-tab-overview").click();
  await expect(page.getByLabel("Agent name")).toHaveValue("Evening wrap-up");
  await expect(page.getByLabel("What it does, in one line")).toHaveValue(
    "Tells you what moved and what's stuck",
  );
  await expect(page.getByTestId("overview-works-on")).toContainText(
    "OmniHarness",
  );
  await expect(page.getByTestId("overview-uses")).toContainText(
    "web · 1 skill",
  );
  await expect(page.getByTestId("overview-next-run")).toContainText(
    "Suggested: Weekdays at 6:00 PM",
  );
  // Tools and skills: only what exists ("teleport" was dropped, and said).
  await page.getByTestId("studio-tab-tools").click();
  await expect(page.getByTestId("agent-tool-groups")).toContainText("web");
  await expect(page.getByTestId("agent-skills")).toContainText(
    "cite-every-claim",
  );
  await expect(page.getByTestId("draft-note")).toContainText("teleport");
  // Autonomy: the suggestion is MARKED, never ticked for the user.
  await page.getByTestId("studio-tab-autonomy").click();
  await expect(page.getByTestId("grant-suggested-tasks")).toBeVisible();
  await expect(
    page.getByTestId("grant-tasks").locator("input"),
  ).not.toBeChecked();
  await expect(page.getByTestId("autonomy-suggested-note")).toContainText(
    "a draft never grants anything",
  );
  // Schedule: suggested, never created.
  await page.getByTestId("studio-tab-schedule").click();
  await expect(page.getByTestId("schedule-suggested")).toContainText(
    "Weekdays at 6:00 PM · America/New_York",
  );
  expect(gateway.agentWrites, "the draft saved something").toEqual([]);

  await page.getByTestId("studio-save").click();
  await expect(page.getByTestId("studio-item-evening-wrap-up")).toHaveAttribute(
    "aria-current",
    "page",
  );
  expect(gateway.agentWrites).toHaveLength(1);
  expect(gateway.agentWrites[0]!.body).toMatchObject({
    name: "evening-wrap-up",
    display_name: "Evening wrap-up",
    soul: "You are my evening wrap-up.\n1. What moved today.\n2. What is stuck.",
    tool_groups: ["web"],
    skills: ["cite-every-claim"],
    projects: ["p-omni"],
    source: "draft",
  });
  // Nothing was granted: the user ticked nothing.
  expect(gateway.autonomyPuts).toEqual([]);
  expect(versionsOf(gateway, "evening-wrap-up")).toHaveLength(1);
});

test("2. editing a tab and saving makes a new version", async ({ page }) => {
  const { gateway } = await setUp(page);
  gateway.seedAgent({
    name: "researcher",
    display_name: "Researcher",
    soul: "You find sources.",
  });
  await openPanel(page, "agents", "researcher");
  await page.getByTestId("studio-tab-instructions").click();
  await page
    .getByTestId("agent-instructions")
    .fill("You find sources and cite every one.");
  await page.getByTestId("studio-save").click();
  await expect(page.getByTestId("studio-saved")).toContainText(
    "Saved as version 2",
  );
  const versions = versionsOf(gateway, "researcher");
  expect(versions.map((v) => v.version)).toEqual([1, 2]);
  expect(versions[1]!.snapshot.soul).toBe(
    "You find sources and cite every one.",
  );
  expect(versions[1]!.changed).toEqual(["soul"]);
  // The History list shows it.
  await page.getByTestId("studio-history").click();
  await expect(page.getByTestId("studio-version").first()).toContainText(
    "v2 · You edited",
  );
});

test("3. a new agent is in the chat bar's @ list, and choosing it joins the chat", async ({
  page,
}) => {
  const { calls } = await setUp(page);
  await page.goto(`/workspace/chats/${THREAD}`);
  const textarea = page.getByLabel("Message", { exact: true });
  // The @ list is read once before the agent exists...
  await textarea.fill("@");
  await expect(page.getByTestId("suggest-menu")).toContainText(
    "Call in an agent",
  );
  await expect(
    page.getByTestId("suggest-menu").getByRole("option", {
      name: /evening-wrap-up/,
    }),
  ).toHaveCount(0);
  await textarea.fill("");
  // ...then the agent is created in Agent Studio, over this chat.
  await page.locator('[data-capsule="agents"]').click();
  await draftNewAgent(page);
  await page.getByTestId("studio-save").click();
  await expect(page.getByTestId("studio-item-evening-wrap-up")).toHaveAttribute(
    "aria-current",
    "page",
  );
  await page.getByTestId("panel-close").click();
  await expect(page.getByTestId("panel-sheet")).toHaveCount(0);

  await textarea.fill("@even");
  const menu = page.getByTestId("suggest-menu");
  const option = menu.getByRole("option", { name: /evening-wrap-up/ });
  await expect(option).toBeVisible();
  await textarea.press("Enter");
  await expect.poll(() => calls).toEqual(["POST evening-wrap-up"]);
  await expect(
    page.getByTestId("chip-agent").filter({ hasText: "evening-wrap-up" }),
  ).toBeVisible();
});

test("4. Undo brings the previous version's content back", async ({ page }) => {
  const { gateway } = await setUp(page);
  gateway.seedAgent({
    name: "researcher",
    display_name: "Researcher",
    soul: "You find sources.",
  });
  await openPanel(page, "agents", "researcher");
  await page.getByTestId("studio-tab-instructions").click();
  const instructions = page.getByTestId("agent-instructions");
  await instructions.fill("Something I will regret.");
  await page.getByTestId("studio-save").click();
  await expect(page.getByTestId("studio-saved")).toContainText(
    "Saved as version 2",
  );
  await page.getByTestId("studio-undo").click();
  await expect(page.getByTestId("studio-undone")).toContainText(
    "version 1 is back",
  );
  await expect(instructions).toHaveValue("You find sources.");
  expect(gateway.undos).toEqual([
    { kind: "agent", name: "researcher", to_version: 1, base_version: 2 },
  ]);
  const versions = versionsOf(gateway, "researcher");
  expect(versions.map((v) => [v.version, v.source])).toEqual([
    [1, "manual"],
    [2, "manual"],
    [3, "undo"],
  ]);
  expect(versions[2]!.snapshot.soul).toBe("You find sources.");
});

test("5. one sentence creates a skill, and Test says Loads or Doesn't load", async ({
  page,
}) => {
  const { gateway } = await setUp(page);
  await openPanel(page, "skills");
  await page.getByTestId("studio-new").click();
  await expect(page.getByTestId("studio-tab-instructions")).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await page
    .getByLabel("Describe the skill in one sentence")
    .fill("How I want project status reported");
  await page
    .getByTestId("skill-draft-bar")
    .getByRole("button", { name: "Draft" })
    .click();
  await expect(page.getByTestId("skill-body")).toHaveValue(/# Status report/);
  await expect(page.getByTestId("studio-title")).toHaveText("Status report");
  await page.getByTestId("studio-tab-details").click();
  await expect(page.getByTestId("skill-name")).toHaveValue("Status report");
  await expect(page.getByTestId("skill-when")).toHaveValue(
    /where a project stands/,
  );
  expect(gateway.skills.has("status-report"), "a draft saved").toBe(false);

  await page.getByTestId("studio-save").click();
  await expect(page.getByTestId("studio-item-status-report")).toHaveAttribute(
    "aria-current",
    "page",
  );
  await page.getByTestId("studio-tab-test").click();
  await page
    .getByTestId("skill-test-input")
    .fill("Where does the launch project stand?");
  await page.getByTestId("skill-test-run").click();
  await expect(page.getByTestId("skill-test-row")).toHaveCount(1);
  await page.getByTestId("skill-test-input").fill("Write a tweet about lunch");
  await page.getByTestId("skill-test-run").click();
  const rows = page.getByTestId("skill-test-row");
  await expect(rows).toHaveCount(2);
  // Newest first.
  await expect(rows.nth(0)).toContainText("“Write a tweet about lunch”");
  await expect(rows.nth(0).getByTestId("skill-test-outcome")).toHaveText(
    "Doesn't load",
  );
  await expect(rows.nth(1)).toContainText(
    "“Where does the launch project stand?”",
  );
  await expect(rows.nth(1).getByTestId("skill-test-outcome")).toHaveText(
    "Loads",
  );
  await expect(rows.nth(1)).toContainText("loaded in 3 of 3 tries");
  expect(gateway.skillTests.map((t) => t.name)).toEqual([
    "status-report",
    "status-report",
  ]);
});

test("6. the picker's Create an agent opens + New agent over the chat, not a page", async ({
  page,
}) => {
  await setUp(page);
  await page.goto(`/workspace/chats/${THREAD}`);
  await page.getByRole("button", { name: "Add context" }).click();
  const picker = page.getByRole("dialog", { name: "Add context" });
  await picker.getByRole("tab", { name: /Agents/ }).click();
  await picker.getByTestId("picker-create-agent").click();
  await expect(page).toHaveURL(
    new RegExp(`/workspace/chats/${THREAD}\\?panel=agents&item=new$`),
  );
  await expect(page.getByTestId("agent-studio")).toBeVisible();
  await expect(page.getByTestId("agent-draft-bar")).toBeVisible();
});
