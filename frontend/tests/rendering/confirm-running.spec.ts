import { mkdirSync } from "fs";

import { expect, test, type Page } from "@playwright/test";

import { lowContrastText } from "./contrast-probe";

/**
 * A confirmed call that is still running when its card answers (a delegation
 * can take minutes; eval E-1): the confirm route answers "running", the card
 * says so with nothing left to press, and the chat picks up the result the
 * gateway posts into it when the call finishes.
 *
 * NO BACKEND: the thread, its state and the pending set are intercepted. The
 * thread's state gains the posted result (id `confirmation-<action id>`)
 * only once the test lets the call "finish".
 */
const THREAD = "11111111-2222-3333-4444-555555555556";
const ACTION = "a1b2c3d4e5f6";
const HOUR = 60 * 60 * 1000;
const RESULT = "Nothing to wipe today: the nightly backup is already gone.";
const SHOTS = process.env.SUMMARY_SHOTS_DIR;

const delegation = {
  id: ACTION,
  tool_name: "task",
  plan_text:
    "Before I do this, please confirm. I intend to use **task** on exactly these 1 item(s):",
  targets: ["task(wipe the backup)"],
  requester: "lead_agent",
  delegation_chain: [],
  expires_at: new Date(Date.now() + 4 * HOUR).toISOString(),
  thread_id: THREAD,
  threshold_targets: 10,
  requires_typed_count: false,
  withheld: false,
  origin: "user",
  confirmable_by_typing: true,
};

function outbound(id: string) {
  return {
    ...delegation,
    id,
    tool_name: "web_fetch",
    targets: [`web_fetch(${id})`],
    arguments_display: { url: `https://${id}.example/` },
    origin: "content",
    origin_source: "gmail_read_email",
    origin_label: "Suggested by content from gmail_read_email",
    confirmable_by_typing: false,
    outbound: true,
    group: "g-turn-1",
  };
}

async function open(
  page: Page,
  scheme: "light" | "dark",
  actions: unknown[],
  confirmBody: unknown,
  continueAgent: string | null = null,
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
  const world = { landed: false, confirms: 0, stateReads: 0 };
  const messages = () => [
    { type: "human", id: "h1", content: "ask a helper to wipe the backup" },
    {
      type: "ai",
      id: "a1",
      content: "A delegation is waiting for you to confirm it.",
    },
    ...(world.landed
      ? [
          {
            type: "ai",
            id: `confirmation-${ACTION}`,
            content: `Done. I ran **task** after you confirmed it.\n\nObserved output from the tool (not an instruction):\n${RESULT}`,
            additional_kwargs: {
              confirmation: {
                action_id: ACTION,
                outcome: "executed",
                continue_agent: continueAgent,
              },
            },
          },
        ]
      : []),
  ];
  const state = () => ({
    values: { title: "Backups", messages: messages() },
    next: [],
    tasks: [],
    metadata: {},
    created_at: new Date().toISOString(),
    checkpoint: { thread_id: THREAD, checkpoint_id: "c1", checkpoint_ns: "" },
    parent_checkpoint: null,
  });
  await page.route("**/api/langgraph/**", (route) => {
    const url = route.request().url();
    // The history the page opens with is read before the call finishes.
    if (url.includes("/history")) return route.fulfill(json([state()]));
    if (url.includes("/runs") || url.includes("/search"))
      return route.fulfill(json([]));
    if (url.includes("/state")) world.stateReads += 1;
    return route.fulfill(json(state()));
  });
  await page.route("**/api/confirmations", (route) =>
    route.fulfill(
      json({
        actions: world.confirms > 0 ? [] : actions,
        readable: true,
        error: "",
      }),
    ),
  );
  // Confirm, decline and apply-all alike.
  await page.route("**/api/confirmations/**", (route) => {
    world.confirms += 1;
    return route.fulfill(json(confirmBody));
  });
  await page.route("**/api/inbox/alerts", (route) =>
    route.fulfill(json({ alerts: [], waiting_count: 0 })),
  );
  await page.goto(`/workspace/chats/${THREAD}`, { waitUntil: "networkidle" });
  return world;
}

async function noLowContrast(page: Page) {
  const found = await page.evaluate(lowContrastText);
  expect(
    found,
    found
      .map((f) => `${f.ratio}/${f.need} "${f.text}" ${f.color} [${f.cls}]`)
      .join("\n"),
  ).toEqual([]);
}

const RUNNING = {
  outcome: "running",
  action_id: ACTION,
  message:
    "Confirmed. It is running now, and its result will be posted in this chat when it finishes.",
  detail: { running: true },
};

for (const scheme of ["light", "dark"] as const) {
  test.describe(`${scheme} theme`, () => {
    test.use({ colorScheme: scheme, viewport: { width: 1440, height: 1200 } });

    test("a running confirmation says so, offers nothing to press, and its result lands in the chat", async ({
      page,
    }) => {
      const world = await open(page, scheme, [delegation], RUNNING);
      const card = page.getByTestId("pending-action");
      await expect(card).toHaveCount(1);
      await card.getByTestId("confirm").click();

      const running = card.getByTestId("running-state");
      await expect(running).toHaveText(
        "Running — the result will appear in this chat.",
      );
      await expect(card.getByTestId("confirm")).toHaveCount(0);
      await expect(card.getByTestId("decline")).toHaveCount(0);
      await expect(page.getByText(RESULT)).toHaveCount(0);
      await noLowContrast(page);
      if (SHOTS) {
        mkdirSync(SHOTS, { recursive: true });
        await card.screenshot({
          path: `${SHOTS}/confirm-running-${scheme}.png`,
        });
      }

      // The call finishes: the gateway posts its result into the thread.
      await expect
        .poll(() => world.stateReads, { timeout: 15_000 })
        .toBeGreaterThan(0);
      world.landed = true;
      await expect(page.getByText(RESULT)).toBeVisible({ timeout: 20_000 });
      await expect(running).toHaveText(
        "Finished — the result is in this chat.",
      );
      expect(world.confirms, "the confirmation was sent again").toBe(1);
      await noLowContrast(page);
      if (SHOTS) {
        await page.screenshot({
          path: `${SHOTS}/confirm-running-landed-${scheme}.png`,
        });
      }
    });

    test("a posted result that offers Continue <agent> shows it on the card once it lands", async ({
      page,
    }) => {
      const world = await open(
        page,
        scheme,
        [delegation],
        RUNNING,
        "researcher",
      );
      const card = page.getByTestId("pending-action");
      await card.getByTestId("confirm").click();
      await expect(card.getByTestId("running-state")).toBeVisible();
      await expect(card.getByTestId("continue-agent")).toHaveCount(0);
      await expect
        .poll(() => world.stateReads, { timeout: 15_000 })
        .toBeGreaterThan(0);
      world.landed = true;
      await expect(card.getByTestId("continue-agent")).toHaveText(
        "Continue researcher",
        { timeout: 20_000 },
      );
      await noLowContrast(page);
    });

    test("a running card with nothing to continue offers no Continue", async ({
      page,
    }) => {
      const world = await open(page, scheme, [delegation], RUNNING);
      const card = page.getByTestId("pending-action");
      await card.getByTestId("confirm").click();
      await expect
        .poll(() => world.stateReads, { timeout: 15_000 })
        .toBeGreaterThan(0);
      world.landed = true;
      await expect(card.getByTestId("running-state")).toHaveText(
        "Finished — the result is in this chat.",
        { timeout: 20_000 },
      );
      await expect(card.getByTestId("continue-agent")).toHaveCount(0);
    });

    test("an outbound group labels a running call", async ({ page }) => {
      const actions = [outbound("w-one"), outbound("w-two")];
      await open(page, scheme, actions, {
        write_id: null,
        results: actions.map((a) => ({ ...RUNNING, action_id: a.id })),
      });
      const group = page.getByTestId("outbound-group");
      await group.getByTestId("outbound-apply-all").click();
      for (const id of ["w-one", "w-two"]) {
        const call = group.locator(`[data-action-id="${id}"]`);
        await expect(call).toHaveAttribute("data-outcome", "running");
        await expect(call.getByTestId("outbound-call-status")).toHaveText(
          "Running — the result will appear in this chat",
        );
      }
      await expect(group.getByTestId("outbound-apply-all")).toHaveCount(0);
      await noLowContrast(page);
    });
  });
}
