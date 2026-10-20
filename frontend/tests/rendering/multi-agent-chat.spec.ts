import { expect, test, type Page } from "@playwright/test";

import { lowContrastText } from "./contrast-probe";

/**
 * Feature 006 Phase 2 — a chat with several agents (Chat.dc.html).
 *
 * - each agent's reply carries its header: avatar in its colour, its name;
 * - a hand-off reads "Lead agent → Researcher";
 * - a confirmation card sits IN the thread where it was raised, styled as the
 *   board's warning-bordered section, with "via lead_agent → researcher";
 * - a chat with the lead alone keeps its plain look (no headers).
 *
 * NO BACKEND: the thread's history and the pending set are intercepted.
 */
const THREAD = "33333333-4444-5555-6666-777777777777";
const ACTION = "abcdef123456";
const HOUR = 60 * 60 * 1000;
const SHOTS =
  "/private/tmp/claude-224110745/-Users-rishabh-sharma-Documents-OmniHarness/2fca2676-46f9-4323-a9df-ccedea8c5376/scratchpad/review/chat";

const MULTI = [
  {
    type: "human",
    id: "h1",
    content: "@researcher how do other tools link subagent sessions?",
  },
  {
    type: "ai",
    id: "a1",
    content: "",
    tool_calls: [
      {
        id: "c1",
        name: "call_agent",
        args: { agent: "researcher", prompt: "how do other tools link?" },
      },
    ],
  },
  {
    type: "tool",
    id: "t1",
    name: "call_agent",
    tool_call_id: "c1",
    content: "Two shapes exist.",
  },
  {
    type: "ai",
    id: "a2",
    name: "researcher",
    content:
      "Two shapes exist. Older rollouts name the parent under `thread_spawn`; newer ones use a different field.",
  },
  { type: "human", id: "h2", content: "@researcher wipe the nightly backup" },
  {
    type: "ai",
    id: "a3",
    name: "researcher",
    content: `I asked to wipe it.\n\n[researcher stopped and is waiting for the user to confirm \`${ACTION}\` (wipe_backup). It has NOT finished its task; nothing it asked about has run.]`,
  },
  { type: "human", id: "h3", content: "thanks" },
  { type: "ai", id: "a4", content: "You're welcome." },
];

const SINGLE = [
  { type: "human", id: "h1", content: "Hello" },
  { type: "ai", id: "a1", content: "Hi, how can I help?" },
];

function pending(id: string) {
  return {
    id,
    tool_name: "wipe_backup",
    plan_text: "I will wipe the backup named nightly.",
    targets: ["nightly"],
    requester: "researcher",
    delegation_chain: ["lead_agent", "researcher"],
    expires_at: new Date(Date.now() + 4 * HOUR - 2 * 60 * 1000).toISOString(),
    thread_id: THREAD,
    threshold_targets: 10,
    requires_typed_count: false,
    withheld: false,
    origin: "user",
    confirmable_by_typing: true,
  };
}

async function open(
  page: Page,
  messages: unknown[],
  actions: unknown[],
  scheme: "light" | "dark" = "dark",
) {
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
  const states = [
    {
      values: { title: "Feature 005 slice review", messages },
      next: [],
      tasks: [],
      metadata: {},
      created_at: new Date().toISOString(),
      checkpoint: { thread_id: THREAD, checkpoint_id: "c1", checkpoint_ns: "" },
      parent_checkpoint: null,
    },
  ];
  await page.route("**/api/langgraph/**", (route) => {
    const url = route.request().url();
    if (url.includes("/history")) return route.fulfill(json(states));
    if (url.includes("/runs") || url.includes("/search"))
      return route.fulfill(json([]));
    return route.fulfill(json(states[0]));
  });
  await page.route("**/api/confirmations", (route) =>
    route.fulfill(json({ actions, readable: true, error: "" })),
  );
  await page.route("**/api/inbox/alerts", (route) =>
    route.fulfill(json({ alerts: [], waiting_count: 0 })),
  );
  await page.goto(`/workspace/chats/${THREAD}`, { waitUntil: "networkidle" });
  await expect(
    page.getByText(String((messages[0] as { content: string }).content)),
  ).toBeVisible();
}

for (const scheme of ["dark", "light"] as const) {
  test.describe(`${scheme} theme`, () => {
    test.use({ colorScheme: scheme, viewport: { width: 1440, height: 900 } });

    test("each agent speaks under its own header, the hand-off is a line, and the card sits where it was raised", async ({
      page,
    }) => {
      await open(page, MULTI, [pending(ACTION)], scheme);

      const headers = page.getByTestId("agent-header");
      await expect(headers.filter({ hasText: "Researcher" })).toHaveCount(2);
      await expect(headers.filter({ hasText: "Lead agent" })).toHaveCount(1);
      // The avatar takes the agent's own colour class (src/core/agents/avatar.ts).
      const avatar = headers.first().locator("span[aria-hidden]").first();
      await expect(avatar).toHaveClass(/bg-avatar-\d/);

      const handoff = page.getByTestId("handoff");
      await expect(handoff).toHaveCount(1);
      await expect(handoff).toHaveAttribute("data-from", "lead_agent");
      await expect(handoff).toHaveAttribute("data-to", "researcher");
      await expect(handoff).toContainText("Lead agent");
      await expect(handoff).toContainText("Researcher");

      // The card is inline: after the reply that raised it, before the next turn.
      const card = page.getByTestId("pending-action");
      await expect(card).toHaveCount(1);
      await expect(
        page.getByTestId("inline-confirmations").getByTestId("pending-action"),
      ).toHaveCount(1);
      const raised = await page.getByText("I asked to wipe it.").boundingBox();
      const cardBox = await card.boundingBox();
      const next = await page.getByText("You're welcome.").boundingBox();
      expect(raised && cardBox && next).toBeTruthy();
      expect(cardBox!.y).toBeGreaterThan(raised!.y);
      expect(cardBox!.y).toBeLessThan(next!.y);

      // Board: warning border, warning title, clock, Decline then Confirm.
      await expect(card).toHaveAttribute("aria-label", "Approval needed");
      await expect(card).toContainText("Needs your approval · wipe_backup");
      await expect(page.getByTestId("remaining")).toHaveText(
        /^Expires in 3h 5\dm$/,
      );
      await expect(page.getByTestId("provenance")).toContainText(
        "via lead_agent → researcher",
      );
      const colours = await card.evaluate((el) => {
        const probe = document.createElement("span");
        probe.className = "text-warning";
        document.body.appendChild(probe);
        const warning = getComputedStyle(probe).color;
        probe.remove();
        return { border: getComputedStyle(el).borderTopColor, warning };
      });
      expect(colours.border).toBe(colours.warning);
      const buttons = card.getByRole("button");
      await expect(buttons.nth(0)).toHaveText("Decline");
      await expect(buttons.nth(1)).toHaveText("Confirm");

      await page.screenshot({
        path: `${SHOTS}/chat-multi-agent-live-${scheme}.png`,
        fullPage: false,
      });
      await page
        .getByText("@researcher how do other tools link subagent sessions?")
        .scrollIntoViewIfNeeded();
      await page.evaluate(() => {
        const el = [...document.querySelectorAll("*")].find(
          (node) =>
            node.scrollHeight > node.clientHeight + 10 &&
            getComputedStyle(node).overflowY !== "visible",
        );
        el?.scrollTo({ top: 0 });
      });
      await page.waitForTimeout(300);
      await page.screenshot({
        path: `${SHOTS}/chat-multi-agent-top-live-${scheme}.png`,
      });
    });

    test("all text in a multi-agent chat meets WCAG AA", async ({ page }) => {
      // Tall enough that nothing scrolls: the probe scrolls each element to
      // the centre, and the thread's stick-to-bottom scrolls it back under
      // the chat bar before it is sampled (it then reads the bar's colour).
      await page.setViewportSize({ width: 1440, height: 2000 });
      await open(page, MULTI, [pending(ACTION)], scheme);
      const isDark = await page.evaluate(() =>
        document.documentElement.classList.contains("dark"),
      );
      expect(isDark).toBe(scheme === "dark");
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

test("a chat with the lead alone keeps its plain look", async ({ page }) => {
  await open(page, SINGLE, []);
  await expect(page.getByText("Hi, how can I help?")).toBeVisible();
  await expect(page.getByTestId("agent-header")).toHaveCount(0);
  await expect(page.getByTestId("handoff")).toHaveCount(0);
});

test("an action no message names is still shown, after the last message", async ({
  page,
}) => {
  await open(page, SINGLE, [pending("000000000000")]);
  await expect(page.getByTestId("pending-action")).toHaveCount(1);
  await expect(page.getByTestId("inline-confirmations")).toHaveCount(0);
});
