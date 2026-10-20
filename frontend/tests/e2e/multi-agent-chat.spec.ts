import { expect, test, type Route } from "@playwright/test";

import { MOCK_RUN_ID, mockLangGraphAPI } from "./utils/mock-api";

/**
 * Feature 006 Phase 2, end to end with a mocked API: the user sends a turn in
 * an existing chat; the run's stream carries the lead's hand-off and the
 * called agent's reply, which stopped to ask; its confirmation card appears
 * IN the thread under that reply, and Confirm resolves it there.
 */
const THREAD = "00000000-0000-0000-0000-0000000000a1";
const ACTION = "abcdef123456";

const STREAMED = [
  {
    type: "human",
    id: "h1",
    content: [{ type: "text", text: "@researcher wipe the nightly backup" }],
  },
  {
    type: "ai",
    id: "a1",
    content: "",
    tool_calls: [
      {
        id: "c1",
        name: "call_agent",
        args: { agent: "researcher", prompt: "wipe the nightly backup" },
      },
    ],
  },
  {
    type: "tool",
    id: "t1",
    name: "call_agent",
    tool_call_id: "c1",
    content: "I asked to wipe it.",
  },
  {
    type: "ai",
    id: "a2",
    name: "researcher",
    content: `I asked to wipe it.\n\n[researcher stopped and is waiting for the user to confirm \`${ACTION}\` (wipe_backup).]`,
  },
];

function stream(route: Route, threadId: string) {
  const events = [
    { event: "metadata", data: { run_id: MOCK_RUN_ID, thread_id: threadId } },
    { event: "values", data: { messages: STREAMED } },
    { event: "end", data: {} },
  ];
  return route.fulfill({
    status: 200,
    contentType: "text/event-stream",
    body: events
      .map((e) => `event: ${e.event}\ndata: ${JSON.stringify(e.data)}\n\n`)
      .join(""),
  });
}

test("a called agent's reply carries its header, and its approval card is confirmed where it was raised", async ({
  page,
}) => {
  mockLangGraphAPI(page, {
    threads: [{ thread_id: THREAD, title: "Backups" }],
  });
  const sent = { thread: "" };
  // After its run the page re-reads the thread: it now holds the run's messages.
  await page.route("**/api/langgraph/threads/*/history", (route) => {
    if (!sent.thread) return route.fallback();
    return route.fulfill({
      json: [
        {
          values: { title: "Backups", messages: STREAMED },
          next: [],
          metadata: {},
          created_at: "2025-01-01T00:00:00Z",
          parent_config: null,
        },
      ],
    });
  });
  await page.route(/\/runs\/stream/, (route) => {
    sent.thread =
      /threads\/([^/]+)\/runs/.exec(route.request().url())?.[1] ?? "";
    return stream(route, sent.thread);
  });
  await page.route("**/api/inbox/alerts", (route) =>
    route.fulfill({ json: { alerts: [], waiting_count: 0 } }),
  );
  const resolved: string[] = [];
  await page.route("**/api/confirmations", (route) => {
    return route.fulfill({
      json: {
        readable: true,
        error: "",
        // Nothing is pending until the run has stated its plan: the card can
        // only appear if the page re-reads the set when the run finishes.
        actions: !sent.thread
          ? []
          : [
              {
                id: ACTION,
                tool_name: "wipe_backup",
                plan_text: "I will wipe the backup named nightly.",
                targets: ["nightly"],
                requester: "researcher",
                delegation_chain: ["lead_agent", "researcher"],
                expires_at: new Date(Date.now() + 3_600_000).toISOString(),
                // The new chat's client-made id, as its run was sent.
                thread_id: THREAD,
                threshold_targets: 10,
                requires_typed_count: false,
                withheld: false,
                origin: "user",
                confirmable_by_typing: true,
              },
            ],
      },
    });
  });
  await page.route("**/api/confirmations/*/confirm", (route) => {
    resolved.push(route.request().url());
    return route.fulfill({
      json: {
        outcome: "executed",
        action_id: ACTION,
        message:
          "Done. researcher ran wipe_backup after you confirmed it.\n\nResult: wiped nightly",
        detail: { result: "wiped nightly" },
      },
    });
  });

  await page.goto(`/workspace/chats/${THREAD}`);
  const textarea = page.getByLabel("Message", { exact: true });
  await expect(textarea).toBeVisible({ timeout: 15_000 });
  await textarea.fill("@researcher wipe the nightly backup");
  await textarea.press("Enter");

  const header = page
    .getByTestId("agent-header")
    .filter({ hasText: "Researcher" });
  await expect(header).toBeVisible({ timeout: 10_000 });
  await expect(page.getByTestId("handoff")).toContainText("Researcher");

  const card = page
    .getByTestId("inline-confirmations")
    .getByTestId("pending-action");
  await expect(card).toBeVisible();
  await expect(card.getByTestId("provenance")).toContainText(
    "via lead_agent → researcher",
  );
  await card.getByTestId("confirm").click();

  await expect.poll(() => resolved.length).toBe(1);
  expect(resolved[0]).toContain(`/api/confirmations/${ACTION}/confirm`);
  // The result is said on the card, in place, and nothing is left to press.
  await expect(card.getByTestId("resolve-message")).toContainText(
    "wiped nightly",
  );
  await expect(card.getByTestId("confirm")).toHaveCount(0);
});
