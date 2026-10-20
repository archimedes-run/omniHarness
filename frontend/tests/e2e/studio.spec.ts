import { expect, test } from "@playwright/test";

import { stubStudio } from "../rendering/studio-stubs";

/**
 * Agent Studio and Skill Studio end to end, against a mocked gateway
 * (Feature 006, Phase 3): what the user does in the panel is what reaches the
 * API, and nothing is written before Save.
 */

test("a new agent is created from the panel with what the user typed", async ({
  page,
}) => {
  const seen = await stubStudio(page);
  await page.goto("/workspace/chats", { waitUntil: "networkidle" });
  await page.locator('[data-capsule="agents"]').click();
  await page.getByTestId("studio-new").click();
  await page.getByLabel("Agent name").fill("Evening digest");
  await page.getByLabel("What it does, in one line").fill("Sums up the day");
  await expect(page.getByText("Saved as evening-digest")).toBeVisible();
  await page.getByTestId("studio-tab-instructions").click();
  await page.getByTestId("agent-instructions").fill("Say what moved today.");
  await page.getByTestId("studio-tab-tools").click();
  await page
    .getByTestId("agent-tool-groups")
    .getByRole("button", { name: "+ Add" })
    .click();
  await page.getByRole("menuitem", { name: "bash" }).click();
  expect(seen.agentWrites, "written before Save").toEqual([]);

  await page.getByTestId("studio-save").click();
  await expect.poll(() => seen.agentWrites.length).toBe(1);
  const [write] = seen.agentWrites;
  expect(write!.method).toBe("POST");
  expect(write!.body).toMatchObject({
    name: "evening-digest",
    display_name: "Evening digest",
    description: "Sums up the day",
    soul: "Say what moved today.",
    tool_groups: ["bash"],
    skills: null,
  });
  await expect(page.getByTestId("studio-item-evening-digest")).toHaveAttribute(
    "aria-current",
    "page",
  );
});

test("editing an agent's projects and skills saves only on Save", async ({
  page,
}) => {
  const seen = await stubStudio(page);
  await page.goto("/workspace/chats?panel=agents&item=evening-wrap-up", {
    waitUntil: "networkidle",
  });
  await page.getByTestId("choose-projects").click();
  await page.getByRole("menuitemcheckbox", { name: "HackMIT 2026" }).click();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("overview-works-on")).toContainText(
    "OmniHarness, HackMIT 2026",
  );
  await page.getByTestId("studio-tab-tools").click();
  await page
    .getByTestId("agent-skills")
    .getByRole("button", { name: "Remove cite-every-claim" })
    .click();
  expect(seen.agentWrites).toEqual([]);
  await expect(page.getByText("Not saved")).toBeVisible();

  await page.getByTestId("studio-save").click();
  await expect.poll(() => seen.agentWrites.length).toBe(1);
  expect(seen.agentWrites[0]!.method).toBe("PUT");
  expect(seen.agentWrites[0]!.url).toContain("/api/agents/evening-wrap-up");
  expect(seen.agentWrites[0]!.body).toMatchObject({
    projects: ["p1", "p2"],
    skills: ["project-status-format"],
    // Made from version 3, by hand: the store refuses it if 3 is stale.
    base_version: 3,
    source: "manual",
  });
});

test("a skill's when-sentence and instructions save as one SKILL.md", async ({
  page,
}) => {
  const seen = await stubStudio(page);
  await page.goto("/workspace/chats?panel=skills&item=project-status-format", {
    waitUntil: "networkidle",
  });
  await page
    .getByTestId("skill-when")
    .fill("Use when someone asks for status.");
  await page.getByTestId("studio-tab-instructions").click();
  await page.getByTestId("skill-body").fill("# Status\n\nOne line first.");
  expect(seen.skillWrites).toEqual([]);
  await page.getByTestId("studio-save").click();
  await expect.poll(() => seen.skillWrites.length).toBe(1);
  const content = (seen.skillWrites[0]!.body as { content: string }).content;
  expect(content).toContain("name: project-status-format");
  expect(content).toContain("description: Use when someone asks for status.");
  expect(content).toContain("# Status\n\nOne line first.");
});

test("a new skill is created under its slug", async ({ page }) => {
  const seen = await stubStudio(page);
  await page.goto("/workspace/chats?panel=skills", {
    waitUntil: "networkidle",
  });
  await page.getByTestId("studio-new").click();
  await page.getByTestId("skill-name").fill("Cite every source");
  await page.getByTestId("skill-when").fill("Use when stating facts.");
  await page.getByTestId("studio-save").click();
  await expect.poll(() => seen.skillWrites.length).toBe(1);
  expect(seen.skillWrites[0]!.method).toBe("POST");
  expect(seen.skillWrites[0]!.body).toMatchObject({
    name: "cite-every-source",
  });
});

test("Draft fills the fields from one sentence for review, and only Save writes", async ({
  page,
}) => {
  const seen = await stubStudio(page);
  await page.goto("/workspace/chats?panel=agents", {
    waitUntil: "networkidle",
  });
  await page.getByTestId("studio-new").click();
  await page
    .getByLabel("Describe the agent in one sentence")
    .fill("Every morning, tell me what is waiting");
  await page
    .getByTestId("agent-draft-bar")
    .getByRole("button", { name: "Draft" })
    .click();
  await expect(page.getByTestId("draft-note")).toContainText(
    "Drafted by default.",
  );
  await expect(page.getByTestId("draft-note")).toContainText(
    "Nothing is saved yet.",
  );
  await expect(page.getByTestId("draft-note")).toContainText("teleport");
  await expect(page.getByTestId("agent-instructions")).toHaveValue(
    "You are my morning brief.\n1. What is waiting.",
  );
  await expect(page.getByLabel("Agent name")).toHaveValue("Morning brief");
  expect(seen.drafts).toEqual([
    {
      kind: "agent",
      sentence: "Every morning, tell me what is waiting",
      agent_name: null,
    },
  ]);
  expect(seen.agentWrites, "a draft saved something").toEqual([]);

  await page.getByTestId("studio-save").click();
  await expect.poll(() => seen.agentWrites.length).toBe(1);
  expect(seen.agentWrites[0]!.body).toMatchObject({
    name: "morning-brief",
    soul: "You are my morning brief.\n1. What is waiting.",
    tool_groups: ["web"],
    skills: ["cite-every-claim"],
    source: "draft",
  });
});

test("a skill's when-sentence is drafted for review, not saved", async ({
  page,
}) => {
  const seen = await stubStudio(page);
  await page.goto("/workspace/chats?panel=skills&item=project-status-format", {
    waitUntil: "networkidle",
  });
  await page.getByTestId("skill-when-draft").click();
  await expect(page.getByTestId("skill-when")).toHaveValue(
    "Use when someone asks where things stand.",
  );
  expect(seen.skillWrites).toEqual([]);
  await page.getByTestId("studio-save").click();
  await expect.poll(() => seen.skillWrites.length).toBe(1);
  expect((seen.skillWrites[0]!.body as { content: string }).content).toContain(
    "description: Use when someone asks where things stand.",
  );
});

test("History restores an earlier version as a new one", async ({ page }) => {
  const seen = await stubStudio(page);
  await page.goto("/workspace/chats?panel=agents&item=evening-wrap-up", {
    waitUntil: "networkidle",
  });
  await page.getByTestId("studio-history").click();
  const rows = page.getByTestId("studio-version");
  await expect(rows).toHaveCount(3);
  await expect(rows.nth(0)).toContainText("v3 · You saved from a draft");
  await expect(rows.nth(0)).toBeDisabled();
  await expect(rows.nth(1)).toContainText(
    "v2 · The agent (evening-wrap-up) changed itself",
  );
  await rows.nth(2).click();
  await expect.poll(() => seen.undos.length).toBe(1);
  expect(seen.undos[0]!.url).toContain("/api/agents/evening-wrap-up/undo");
  expect(seen.undos[0]!.body).toEqual({ to_version: 1, base_version: 3 });
  await expect(page.getByTestId("studio-history-note")).toHaveText(
    "Restored version 1 as a new version.",
  );
});

test("a save made from an old version is refused and says so", async ({
  page,
}) => {
  await stubStudio(page, { staleAgents: true });
  await page.goto("/workspace/chats?panel=agents&item=evening-wrap-up", {
    waitUntil: "networkidle",
  });
  await page.getByLabel("What it does, in one line").fill("Changed here");
  await page.getByTestId("studio-save").click();
  await expect(page.getByTestId("studio-save-error")).toContainText(
    "changed since you opened it",
  );
});

test("granting a reversible action saves as a new version, from the one shown", async ({
  page,
}) => {
  const seen = await stubStudio(page);
  await page.goto("/workspace/chats?panel=agents&item=evening-wrap-up", {
    waitUntil: "networkidle",
  });
  await page.getByTestId("studio-tab-autonomy").click();
  await expect(page.getByTestId("grant-tasks").locator("input")).toBeChecked();
  await expect(page.getByTestId("grant-archive")).toContainText(
    "Changing its status brings it back.",
  );
  await expect(page.getByTestId("always-waits")).toContainText(
    "github_create_issue",
  );
  await page.getByRole("button", { name: "Show all 10" }).click();
  await expect(page.getByTestId("always-waits")).toContainText(
    "github_merge_pull_request",
  );
  await page.getByTestId("grant-archive").locator("input").check();
  await page.getByTestId("grant-notes").locator("input").uncheck();
  expect(seen.autonomyPuts).toEqual([]);
  await page.getByTestId("studio-save").click();
  await expect.poll(() => seen.autonomyPuts.length).toBe(1);
  expect(seen.autonomyPuts[0]).toEqual({
    agent: "evening-wrap-up",
    granted: ["tasks", "archive"],
    base_version: 3,
  });
  expect(seen.agentWrites, "an unchanged agent was rewritten").toEqual([]);
});

test("an agent edit and a grant saved together chain their versions", async ({
  page,
}) => {
  const seen = await stubStudio(page);
  await page.goto("/workspace/chats?panel=agents&item=evening-wrap-up", {
    waitUntil: "networkidle",
  });
  await page.getByLabel("What it does, in one line").fill("Wraps up the day");
  await page.getByTestId("studio-tab-autonomy").click();
  await page.getByTestId("grant-archive").locator("input").check();
  await page.getByTestId("studio-save").click();
  await expect.poll(() => seen.autonomyPuts.length).toBe(1);
  expect(seen.agentWrites[0]!.body).toMatchObject({ base_version: 3 });
  // The agent edit made version 4; the grant is based on it, not on 3.
  expect(seen.autonomyPuts[0]).toMatchObject({ base_version: 4 });
});

test("Skill Test runs only when Test is pressed and reports what it observed", async ({
  page,
}) => {
  const seen = await stubStudio(page);
  await page.goto("/workspace/chats?panel=skills&item=project-status-format", {
    waitUntil: "networkidle",
  });
  await page.getByTestId("studio-tab-test").click();
  await page.getByTestId("skill-test-input").fill("Wrap up my day");
  await page.waitForTimeout(500);
  expect(seen.tests, "a test ran without the button").toEqual([]);
  await page.getByTestId("skill-test-run").click();
  await expect.poll(() => seen.tests.length).toBe(1);
  expect(seen.tests[0]).toEqual({ message: "Wrap up my day", tries: 3 });
  const row = page.getByTestId("skill-test-row").first();
  await expect(row).toContainText("“Wrap up my day”");
  await expect(row).toContainText("Loaded 2 of 3");
  await expect(row).toContainText("Observed with default");
  await expect(row).toContainText("also opened cite-every-claim");
});
