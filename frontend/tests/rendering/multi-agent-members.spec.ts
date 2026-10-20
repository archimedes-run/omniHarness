import { expect, test, type Page } from "@playwright/test";

import { lowContrastText } from "./contrast-probe";

/**
 * Feature 006 Phase 2 — who is in a chat, as Chat.dc.html shows it: the
 * header's overlapping avatars and "3 agents"; a chip per agent in the chat
 * bar; the "@" menu titled "Call in an agent", members marked "In this chat".
 *
 * NO BACKEND: history, membership, agents and the pending set are intercepted.
 */
const THREAD = "44444444-5555-6666-7777-888888888888";
const SHOTS =
  "/private/tmp/claude-224110745/-Users-rishabh-sharma-Documents-OmniHarness/2fca2676-46f9-4323-a9df-ccedea8c5376/scratchpad/review/chat";
const HOUR = 60 * 60 * 1000;

const MESSAGES = [
  {
    type: "human",
    id: "h1",
    content:
      "@researcher how do other tools link Codex subagent sessions to their parent?",
  },
  {
    type: "ai",
    id: "a1",
    content: "",
    tool_calls: [
      {
        id: "c1",
        name: "call_agent",
        args: { agent: "researcher", prompt: "x" },
      },
    ],
  },
  {
    type: "tool",
    id: "t1",
    name: "call_agent",
    tool_call_id: "c1",
    content: "x",
  },
  {
    type: "ai",
    id: "a2",
    name: "researcher",
    content:
      "Two shapes exist. Older rollouts name the parent under `thread_spawn`; newer ones use a different field. Read both.",
  },
  {
    type: "human",
    id: "h2",
    content: "@release-manager given that, can Slice 1 still ship this week?",
  },
  {
    type: "ai",
    id: "a3",
    name: "release-manager",
    content:
      "Yes, if the parent-link change lands by Wednesday. 3 of 7 Slice 1 tasks are done (observed).\n\n[release-manager stopped and is waiting for the user to confirm `abcdef123456` (slack_post). It has NOT finished its task; nothing it asked about has run.]",
  },
];

async function open(page: Page, scheme: "light" | "dark") {
  const json = (body: unknown) => ({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
  await page.addInitScript((t) => {
    try {
      localStorage.setItem("theme", t);
    } catch {}
  }, scheme);
  const state = {
    values: { title: "Feature 005 slice review", messages: MESSAGES },
    next: [],
    tasks: [],
    metadata: {},
    created_at: new Date().toISOString(),
    checkpoint: { thread_id: THREAD, checkpoint_id: "c1", checkpoint_ns: "" },
    parent_checkpoint: null,
  };
  await page.route("**/api/langgraph/**", (route) => {
    const url = route.request().url();
    if (url.includes("/history")) return route.fulfill(json([state]));
    if (url.includes("/runs") || url.includes("/search"))
      return route.fulfill(json([]));
    return route.fulfill(json(state));
  });
  await page.route("**/api/threads/*/participants", (route) =>
    route.fulfill(
      json({
        thread_id: THREAD,
        participants: [
          { name: "lead_agent", description: "Leads this chat", lead: true },
          { name: "researcher", description: "", lead: false },
          { name: "release-manager", description: "", lead: false },
        ],
      }),
    ),
  );
  await page.route("**/api/agents", (route) =>
    route.fulfill(
      json({
        agents: [
          {
            name: "evening-wrap-up",
            description: "Project status · GitHub, Calendar",
          },
          { name: "researcher", description: "Web search · GitHub" },
          { name: "release-manager", description: "OmniHarness project" },
        ],
      }),
    ),
  );
  await page.route("**/api/confirmations", (route) =>
    route.fulfill(
      json({
        readable: true,
        error: "",
        actions: [
          {
            id: "abcdef123456",
            tool_name: "slack_post",
            plan_text: "I will post the Slice 1 plan to #omniharness.",
            targets: ["#omniharness"],
            requester: "release-manager",
            delegation_chain: ["lead_agent", "release-manager"],
            expires_at: new Date(
              Date.now() + 4 * HOUR - 2 * 60_000,
            ).toISOString(),
            thread_id: THREAD,
            threshold_targets: 10,
            requires_typed_count: false,
            withheld: false,
            origin: "user",
            confirmable_by_typing: true,
          },
        ],
      }),
    ),
  );
  await page.route("**/api/inbox/alerts", (route) =>
    route.fulfill(json({ alerts: [], waiting_count: 0 })),
  );
  await page.goto(`/workspace/chats/${THREAD}`, { waitUntil: "networkidle" });
  await expect(
    page.getByText("Two shapes exist.", { exact: false }),
  ).toBeVisible();
}

for (const scheme of ["dark", "light"] as const) {
  test.describe(`${scheme} theme`, () => {
    test.use({ colorScheme: scheme, viewport: { width: 1440, height: 900 } });

    test("the header names the chat's agents, the bar has a chip each, and @ calls one in", async ({
      page,
    }) => {
      await open(page, scheme);

      const stack = page.getByTestId("participants");
      await expect(stack).toContainText("3 agents");
      await expect(stack.getByRole("img")).toHaveAttribute(
        "aria-label",
        "Agents in this chat: Lead agent, Researcher, Release manager",
      );
      const chips = page.getByTestId("chip-agent");
      await expect(chips).toHaveCount(3);
      await expect(
        page.getByRole("button", { name: "Remove researcher from this chat" }),
      ).toBeVisible();
      await expect(
        page.getByRole("button", {
          name: "Remove release-manager from this chat",
        }),
      ).toBeVisible();

      const textarea = page.getByLabel("Message", { exact: true });
      await textarea.fill("@e");
      const menu = page.getByTestId("suggest-menu");
      await expect(menu).toContainText("Call in an agent");
      await expect(
        menu.getByRole("option", { name: /researcher/ }),
      ).toContainText("In this chat");
      await expect(
        menu.getByRole("option", { name: /evening-wrap-up/ }),
      ).toContainText("Project status");

      await page.screenshot({
        path: `${SHOTS}/chat-members-live-${scheme}.png`,
      });
    });

    test("all text with the @ menu open meets WCAG AA", async ({ page }) => {
      await page.setViewportSize({ width: 1440, height: 2000 });
      await open(page, scheme);
      await page.getByLabel("Message", { exact: true }).fill("@e");
      await expect(page.getByTestId("suggest-menu")).toBeVisible();
      const found = await page.evaluate(lowContrastText);
      expect(
        found,
        found
          .map((f) => `${f.ratio}/${f.need} "${f.text}" ${f.color} [${f.cls}]`)
          .join("\n"),
      ).toEqual([]);
    });
  });
}
