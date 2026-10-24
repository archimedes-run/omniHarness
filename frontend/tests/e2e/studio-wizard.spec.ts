import { expect, test, type Page } from "@playwright/test";

import { stubStudio } from "../rendering/studio-stubs";

/**
 * The Agent & Skill Studio (006-G) end to end, against a stateful stand-in
 * for the gateway (tests/rendering/studio-stubs.ts): what the person does in
 * the steppers is exactly what reaches the API, and nothing is written before
 * they save.
 */

test.use({ timezoneId: "America/New_York" });

const WRAP_UP_RULE = {
  id: "evening-wrap-up-schedule",
  agent: "evening-wrap-up",
  schedule: "30 18 * * 1-5",
  timezone: "America/New_York",
  destination: "auto",
  show_on_home: true,
  enabled: true,
  prompt: "Write today's wrap-up.",
  fired: true,
};

async function openAgents(page: Page, item?: string) {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(
    `/workspace/chats?panel=agents${item ? `&item=${encodeURIComponent(item)}` : ""}`,
    { waitUntil: "networkidle" },
  );
}

test("a new agent made through all four steps saves its avatar, Gmail tools, a schedule and a grant", async ({
  page,
}) => {
  const seen = await stubStudio(page);
  await openAgents(page);
  await page.getByTestId("agents-new").click();

  // Step 1: a face, a name, instructions.
  await page.getByTestId("avatar-change").click();
  await page.locator('[data-avatar-id="croak"]').click();
  await page.getByTestId("agent-name").fill("Inbox zero coach");
  await page
    .getByTestId("agent-sentence")
    .fill(
      "Keeps my inbox near zero by labelling routine mail and drafting replies.",
    );
  await page
    .getByTestId("agent-instructions")
    .fill("Label routine email and draft replies. Never send.");
  await page.getByTestId("wizard-next").click();

  // Step 2: Gmail on (what does not ask first), plus Move to trash by hand.
  await page.getByTestId("integration-switch-connector:GMAIL").click();
  await expect(
    page.getByTestId("tool-switch-connector-gmail_GMAIL_FETCH_EMAILS"),
  ).toHaveAttribute("aria-checked", "true");
  // Asks-first tools arrive unticked; a tool no rule names can't be ticked.
  await expect(
    page.getByTestId("tool-switch-connector-gmail_GMAIL_MOVE_TO_TRASH"),
  ).toHaveAttribute("aria-checked", "false");
  await page.getByTestId("integration-all-connector:GMAIL").click();
  await expect(
    page.getByTestId("tool-switch-connector-gmail_GMAIL_SEND_EMAIL"),
  ).toBeDisabled();
  await page
    .getByTestId("tool-switch-connector-gmail_GMAIL_MOVE_TO_TRASH")
    .click();
  await expect(
    page.getByText("On a schedule this waits on Home for your OK."),
  ).toBeVisible();
  await page.getByTestId("config-tab-skills").click();
  await page.getByTestId("skill-switch-project-status-format").click();
  await page.getByTestId("config-tab-autonomy").click();
  // Drafting is allowed now that a draft tool is on (owner decision 5).
  await page.getByTestId("grant-drafts").click();
  await expect(page.getByTestId("grant-drafts")).toHaveAttribute(
    "aria-checked",
    "true",
  );
  await page.getByTestId("wizard-next").click();

  // Step 3: a weekly schedule on Monday and Wednesday at 8:30.
  await page.getByTestId("schedule-quick-weekly").click();
  await page.getByTestId("schedule-time").fill("08:30");
  await page.locator('[data-day="3"]').click();
  await page.getByTestId("schedule-zone").selectOption("America/Chicago");
  await expect(page.getByTestId("schedule-readout")).toContainText(
    "Every Mon and Wed at 8:30 AM CDT",
  );
  await page.getByTestId("schedule-task").fill("List what is waiting on me.");
  await page.getByTestId("schedule-save").click();
  await expect(page.getByTestId("schedule-card")).toHaveCount(1);
  await page.getByTestId("wizard-next").click();

  // Step 4: Home off for new schedules; nothing has been written yet.
  await page.getByTestId("notify-home").click();
  expect(seen.agentWrites, "written before Create agent").toEqual([]);
  expect(seen.rules.writes, "a schedule written before Create agent").toEqual(
    [],
  );
  await page.getByTestId("wizard-save").click();

  await expect.poll(() => seen.agentWrites.length).toBe(1);
  const [write] = seen.agentWrites;
  expect(write!.method).toBe("POST");
  expect(write!.body).toEqual({
    name: "inbox-zero-coach",
    display_name: "Inbox zero coach",
    description:
      "Keeps my inbox near zero by labelling routine mail and drafting replies.",
    soul: "Label routine email and draft replies. Never send.",
    avatar: "croak",
    skills: ["project-status-format"],
    notify: { telegram: true, home: false },
    tools: {
      integrations: ["connector:GMAIL"],
      tools: [
        "connector-gmail_GMAIL_ADD_LABEL_TO_EMAIL",
        "connector-gmail_GMAIL_CREATE_EMAIL_DRAFT",
        "connector-gmail_GMAIL_FETCH_EMAILS",
        "connector-gmail_GMAIL_FETCH_MESSAGE_BY_THREAD_ID",
        "connector-gmail_GMAIL_GET_PROFILE",
        "connector-gmail_GMAIL_LIST_LABELS",
        "connector-gmail_GMAIL_MOVE_TO_TRASH",
      ],
    },
    source: "manual",
  });
  await expect.poll(() => seen.autonomyPuts.length).toBe(1);
  expect(seen.autonomyPuts[0]).toEqual({
    agent: "inbox-zero-coach",
    granted: ["drafts"],
    base_version: 1,
  });
  await expect.poll(() => seen.rules.writes.length).toBe(1);
  expect(seen.rules.writes[0]).toMatchObject({
    method: "POST",
    agent: "inbox-zero-coach",
    body: {
      schedule: "30 8 * * 1,3",
      timezone: "America/Chicago",
      telegram: true,
      show_on_home: true,
      prompt: "List what is waiting on me.",
      enabled: true,
      version: "v1",
    },
  });
  // Back on the list, the new agent is there with its face and status.
  await expect(page.getByTestId("agent-card-inbox-zero-coach")).toContainText(
    "Scheduled",
  );
  await expect(
    page
      .getByTestId("agent-card-inbox-zero-coach")
      .locator('img[src="/avatars/croak.svg"]'),
  ).toBeVisible();
});

test("one sentence drafts every step for review: grants unticked, the schedule made only on Create, Undo draft restores", async ({
  page,
}) => {
  const seen = await stubStudio(page);
  await openAgents(page, "new");
  await page
    .getByTestId("agent-sentence")
    .fill(
      "Every weekday morning, scan my inbox and calendar and send me a five-line plan.",
    );
  await page.getByTestId("agent-draft").click();
  await expect(page.getByTestId("agent-drafted")).toBeVisible();
  await expect(page.getByTestId("agent-name")).toHaveValue("Morning planner");
  await expect(page.getByTestId("wizard-step-2")).toContainText("Drafted");
  expect(seen.drafts).toEqual([
    {
      kind: "agent",
      body: {
        sentence:
          "Every weekday morning, scan my inbox and calendar and send me a five-line plan.",
        agent_name: null,
      },
    },
  ]);
  await page.getByTestId("wizard-step-2").click();
  await expect(page.getByTestId("config-tab-integrations")).toContainText(
    "2 integrations",
  );
  await page.getByTestId("config-tab-autonomy").click();
  // Suggested, never ticked for the person.
  await expect(page.getByTestId("grant-tasks")).toHaveAttribute(
    "aria-checked",
    "false",
  );
  await expect(page.getByTestId("grant-tasks")).toContainText(
    "Suggested by Draft",
  );
  await page.getByTestId("wizard-step-3").click();
  await expect(page.getByTestId("schedule-card")).toContainText(
    "Every weekday at 8:00 AM",
  );
  expect(seen.agentWrites).toEqual([]);
  expect(seen.rules.writes).toEqual([]);

  await page.getByTestId("wizard-step-1").click();
  await page.getByTestId("agent-undo-draft").click();
  await expect(page.getByTestId("agent-name")).toHaveValue("");
  await expect(page.getByTestId("agent-instructions")).toHaveValue("");
});

test("edit mode: jump to a step, see what is unsaved, and save from any step with ⌘S", async ({
  page,
}) => {
  const seen = await stubStudio(page, { schedules: [WRAP_UP_RULE] });
  await openAgents(page, "evening-wrap-up");
  // Every step is reachable at once.
  await page.getByTestId("wizard-step-3").click();
  await expect(page.getByTestId("schedule-card")).toContainText(
    "Every weekday at 6:30 PM",
  );
  await page.getByTestId("schedule-edit").click();
  await page.getByTestId("schedule-time").fill("19:00");
  await page.getByTestId("schedule-save").click();
  await expect(page.getByTestId("wizard-step-3")).toHaveAttribute(
    "data-dirty",
    "1",
  );
  await expect(page.getByTestId("wizard-unsaved")).toBeVisible();
  await page.getByTestId("wizard-step-1").click();
  await page.getByTestId("agent-name").fill("Evening digest");
  await expect(page.getByTestId("wizard-step-1")).toHaveAttribute(
    "data-dirty",
    "1",
  );
  // ⌘S from step 1 saves both.
  await page.keyboard.press("ControlOrMeta+s");
  await expect.poll(() => seen.agentWrites.length).toBe(1);
  // Only what changed, made from the version shown.
  expect(seen.agentWrites[0]!.body).toEqual({
    display_name: "Evening digest",
    base_version: 1,
    source: "manual",
  });
  await expect.poll(() => seen.rules.writes.length).toBe(1);
  expect(seen.rules.writes[0]).toMatchObject({
    method: "PUT",
    agent: "evening-wrap-up",
    body: { schedule: "0 19 * * 1-5", version: "v1" },
  });
  await expect(page.getByTestId("wizard-unsaved")).toHaveCount(0);
  await expect(page.getByTestId("wizard-step-3")).not.toHaveAttribute(
    "data-dirty",
    "1",
  );
  // The save toast's Undo brings back the version before it.
  await page
    .getByTestId("studio-toast")
    .getByRole("button", { name: "Undo" })
    .click();
  await expect.poll(() => seen.undos.length).toBe(1);
  expect(seen.undos[0]!.body).toEqual({ to_version: 1, base_version: 2 });
});

test("a save made from an old version is refused and says so", async ({
  page,
}) => {
  await stubStudio(page, { staleAgents: true });
  await openAgents(page, "evening-wrap-up");
  await page.getByTestId("agent-name").fill("Stale edit");
  await page.keyboard.press("ControlOrMeta+s");
  await expect(page.getByTestId("wizard-save-error")).toContainText(
    "changed since you opened it",
  );
});

test("an agent saved before 006-G keeps its tool groups unless a tick changes", async ({
  page,
}) => {
  const seen = await stubStudio(page);
  await openAgents(page, "researcher");
  await page.getByTestId("wizard-step-2").click();
  await expect(page.getByTestId("legacy-note")).toBeVisible();
  await page.getByTestId("wizard-step-1").click();
  await page.getByTestId("agent-instructions").fill("You research and cite.");
  await page.keyboard.press("ControlOrMeta+s");
  await expect.poll(() => seen.agentWrites.length).toBe(1);
  expect(seen.agentWrites[0]!.body).not.toHaveProperty("tools");
  // Now a tick changes: the allowlist is written, from the ticks shown.
  await page.getByTestId("wizard-step-2").click();
  await page.getByTestId("integration-expand-builtin:web").click();
  await page.getByTestId("tool-switch-web_fetch").click();
  await page.keyboard.press("ControlOrMeta+s");
  await expect.poll(() => seen.agentWrites.length).toBe(2);
  expect(seen.agentWrites[1]!.body.tools).toEqual({
    integrations: ["builtin:ledger", "builtin:web", "local:filesystem"],
    tools: [
      "filesystem_edit_file",
      "filesystem_read_file",
      "ledger_apply",
      "ledger_read",
      "web_search",
    ],
  });
});

test("the skill stepper: a new skill from one sentence, saved, then tested three times and kept", async ({
  page,
}) => {
  const seen = await stubStudio(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/workspace/chats?panel=skills", {
    waitUntil: "networkidle",
  });
  await page.getByTestId("skills-new").click();
  await page.getByTestId("skill-name").fill("Release notes");
  await page
    .getByTestId("skill-when")
    .fill("When summarising merged pull requests for a release.");
  await page.locator('[data-glyph="rocket"]').click();
  await page.getByTestId("wizard-next").click();
  await page
    .getByTestId("skill-sentence")
    .fill("Group merged PRs by area and link each one.");
  await page.getByTestId("skill-draft").click();
  await expect(page.getByTestId("skill-body")).toHaveValue(/## Release notes/);
  await page.getByTestId("wizard-next").click();
  await page.getByTestId("skill-file-input").setInputFiles({
    name: "changelog-style.md",
    mimeType: "text/markdown",
    buffer: Buffer.from("# Style\nShort lines."),
  });
  await expect(page.getByTestId("skill-file")).toContainText(
    "changelog-style.md",
  );
  await page.getByTestId("wizard-next").click();
  // A new skill is tested once it is saved.
  await expect(page.getByTestId("skill-test-input")).toBeDisabled();
  expect(seen.skillWrites).toEqual([]);
  await page.getByTestId("wizard-save").click();
  await expect.poll(() => seen.skillWrites.length).toBe(3);
  expect(seen.skillWrites[0]).toMatchObject({
    method: "POST",
    body: { name: "release-notes" },
  });
  expect((seen.skillWrites[0]!.body as { content: string }).content).toContain(
    "description: When summarising merged pull requests for a release.",
  );
  expect(seen.skillWrites[1]).toMatchObject({
    method: "PUT",
    body: { icon: "rocket" },
  });
  expect(seen.skillWrites[2]).toMatchObject({
    method: "POST",
    body: { path: "references/changelog-style.md" },
  });

  // Now on the saved skill's Test step.
  await expect(page.getByTestId("skill-test-input")).toBeEnabled();
  await page
    .getByTestId("skill-test-input")
    .fill("Where are we on the release?");
  await page.getByTestId("skill-test-run").click();
  await expect(page.getByTestId("skill-test-row")).toContainText(
    "Loads · 3 of 3",
  );
  expect(seen.skillTests).toEqual([
    {
      name: "release-notes",
      message: "Where are we on the release?",
      tries: 3,
      save: true,
    },
  ]);
  // Saved with the skill: it is there when the skill is opened again.
  await page.getByTestId("wizard-back-list").click();
  await page.getByTestId("skill-card-release-notes").click();
  await page.getByTestId("wizard-step-4").click();
  await expect(page.getByTestId("skill-test-row")).toContainText(
    "Where are we on the release?",
  );
});

test("Agents | Skills switches inside the one modal, and the palette's New agent opens the stepper", async ({
  page,
}) => {
  await stubStudio(page);
  await openAgents(page);
  await page.getByTestId("studio-switch-skills").click();
  await expect(page.getByTestId("skills-list")).toBeVisible();
  await expect(page).toHaveURL(/panel=skills/);
  await page.getByTestId("studio-switch-agents").click();
  await expect(page.getByTestId("agents-list")).toBeVisible();
  // `item=new` arriving while the panel is open (palette, picker).
  await page.evaluate(() => {
    const url = new URL(window.location.href);
    url.searchParams.set("item", "new");
    window.history.pushState(null, "", url.toString());
  });
  await expect(page.getByTestId("agent-step-setup")).toBeVisible();
  await expect(page.getByTestId("wizard-title")).toHaveText("Untitled agent");
});

test("the agent's avatar replaces the initials in Automations' Runs as", async ({
  page,
}) => {
  await stubStudio(page, { schedules: [WRAP_UP_RULE] });
  await page.goto("/workspace/automations", { waitUntil: "networkidle" });
  const runsAs = page.getByTestId("rule-runs-as").first();
  await expect(runsAs).toContainText("Runs as Evening wrap-up");
  await expect(runsAs.locator("img")).toHaveAttribute(
    "src",
    "/avatars/snooze.svg",
  );
});

test("the lead agent keeps its fixed tools and instructions; its grants are still set here", async ({
  page,
}) => {
  const seen = await stubStudio(page);
  await openAgents(page);
  await page.getByTestId("agent-card-lead_agent").click();
  await expect(page.getByTestId("wizard-title")).toHaveText("Lead agent");
  await expect(page.getByTestId("agent-instructions")).toHaveCount(0);
  await page.getByTestId("wizard-step-2").click();
  // Only Autonomy: its tools are not chosen here.
  await expect(page.getByTestId("config-tab-integrations")).toHaveCount(0);
  await page.getByTestId("grant-tasks").click();
  await page.keyboard.press("ControlOrMeta+s");
  await expect.poll(() => seen.autonomyPuts.length).toBe(1);
  expect(seen.autonomyPuts[0]).toEqual({
    agent: "lead_agent",
    granted: ["tasks"],
    base_version: 0,
  });
  expect(seen.agentWrites).toEqual([]);
});
