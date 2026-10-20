import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

/**
 * Feature 006 Phase 2, end to end with a mocked API: who is in a chat is the
 * THREAD's state on the server (/api/threads/{id}/participants).
 *
 * - "@" in an existing chat calls an agent in: it is added on the server and
 *   appears as a removable chip; its × takes it out on the server;
 * - the header shows the chat's agents;
 * - a confirmed card for an agent that stopped offers "Continue <agent>",
 *   which sends an ordinary user turn mentioning it;
 * - a card refused because its tool was removed from the chat says why and
 *   keeps its buttons.
 */
const THREAD = "00000000-0000-0000-0000-0000000000b2";
const AGENTS = [
  { name: "researcher", description: "Web search · GitHub" },
  { name: "release-manager", description: "OmniHarness project" },
];

async function setUp(page: Page, initialMembers: string[]) {
  mockLangGraphAPI(page, {
    threads: [{ thread_id: THREAD, title: "Slice review" }],
    agents: AGENTS,
  });
  const members = [...initialMembers];
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
  await page.route("**/api/threads/*/participants/*", (route) => {
    const agent = decodeURIComponent(route.request().url().split("/").pop()!);
    calls.push(`DELETE ${agent}`);
    members.splice(members.indexOf(agent), 1);
    return route.fulfill({ json: view() });
  });
  await page.route("**/api/inbox/alerts", (route) =>
    route.fulfill({ json: { alerts: [], waiting_count: 0 } }),
  );
  return { members, calls };
}

test("@ in an existing chat calls an agent in, and its chip takes it out", async ({
  page,
}) => {
  const state = await setUp(page, []);
  await page.route("**/api/confirmations", (route) =>
    route.fulfill({ json: { actions: [], readable: true, error: "" } }),
  );
  await page.goto(`/workspace/chats/${THREAD}`);
  const textarea = page.getByLabel("Message", { exact: true });
  await expect(textarea).toBeVisible({ timeout: 15_000 });

  await textarea.fill("@res");
  const menu = page.getByTestId("suggest-menu");
  await expect(menu).toContainText("Call in an agent");
  await expect(menu).not.toContainText("arrives with multi-agent chat");
  const option = menu.getByRole("option", { name: /researcher/ });
  await expect(option).not.toHaveAttribute("aria-disabled", "true");
  await textarea.press("Enter");

  await expect.poll(() => state.calls).toEqual(["POST researcher"]);
  await expect(textarea).toHaveValue("@researcher ");
  const chip = page.getByTestId("chip-agent").filter({ hasText: "researcher" });
  await expect(chip).toBeVisible();
  await expect(page.getByTestId("participants")).toContainText("2 agents");

  await chip
    .getByRole("button", { name: "Remove researcher from this chat" })
    .click();
  await expect
    .poll(() => state.calls)
    .toEqual(["POST researcher", "DELETE researcher"]);
  await expect(chip).toHaveCount(0);
  await expect(page.getByTestId("participants")).toHaveCount(0);
});

function action(id: string) {
  return {
    id,
    tool_name: "wipe_backup",
    plan_text: "I will wipe the backup named nightly.",
    targets: ["nightly"],
    requester: "researcher",
    delegation_chain: ["lead_agent", "researcher"],
    expires_at: new Date(Date.now() + 3_600_000).toISOString(),
    thread_id: THREAD,
    threshold_targets: 10,
    requires_typed_count: false,
    withheld: false,
    origin: "user",
    confirmable_by_typing: true,
  };
}

test("a confirmed card offers Continue <agent>, which sends the user's own turn naming the action", async ({
  page,
}) => {
  await setUp(page, ["researcher"]);
  await page.route("**/api/confirmations", (route) =>
    route.fulfill({
      json: { actions: [action("abcdef123456")], readable: true, error: "" },
    }),
  );
  await page.route("**/api/confirmations/*/confirm", (route) =>
    route.fulfill({
      json: {
        outcome: "executed",
        action_id: "abcdef123456",
        message:
          "Done. researcher ran wipe_backup after you confirmed it. researcher stopped at this step to ask you and has not continued its task.",
        detail: { result: "wiped nightly", continue_agent: "researcher" },
      },
    }),
  );
  const sent: string[] = [];
  await page.route("**/api/langgraph/threads/*/runs/stream", (route) => {
    sent.push(JSON.stringify(route.request().postDataJSON()));
    return route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: "event: end\ndata: {}\n\n",
    });
  });
  await page.goto(`/workspace/chats/${THREAD}`);
  const card = page.getByTestId("pending-action");
  await expect(card).toBeVisible({ timeout: 15_000 });

  await card.getByTestId("confirm").click();
  const proceed = card.getByTestId("continue-agent");
  await expect(proceed).toHaveText("Continue researcher");
  await proceed.click();

  await expect.poll(() => sent.length).toBe(1);
  expect(sent[0]).toContain("Continue researcher.");
  // The server re-enters the agent's own delegation from this id alone.
  expect(sent[0]).toContain('"continue_action":"abcdef123456"');
});

test("a card refused because its tool left the chat says why and keeps its buttons", async ({
  page,
}) => {
  await setUp(page, ["researcher"]);
  await page.route("**/api/confirmations", (route) =>
    route.fulfill({
      json: { actions: [action("abcdef123456")], readable: true, error: "" },
    }),
  );
  await page.route("**/api/confirmations/*/confirm", (route) =>
    route.fulfill({
      json: {
        outcome: "tool_unavailable",
        action_id: "abcdef123456",
        message:
          "wipe_backup is no longer available in this chat: its source was removed from the chat after this was proposed. Nothing has run. Add it back to confirm.",
        detail: {},
      },
    }),
  );
  await page.goto(`/workspace/chats/${THREAD}`);
  const card = page.getByTestId("pending-action");
  await expect(card).toBeVisible({ timeout: 15_000 });

  await card.getByTestId("confirm").click();

  await expect(card.getByTestId("resolve-message")).toContainText(
    "its source was removed from the chat",
  );
  await expect(card.getByTestId("resolve-message")).toHaveAttribute(
    "data-outcome",
    "tool_unavailable",
  );
  await expect(card.getByTestId("confirm")).toBeVisible();
  await expect(card.getByTestId("continue-agent")).toHaveCount(0);
});
