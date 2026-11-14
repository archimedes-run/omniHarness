import { mkdirSync } from "fs";

import { expect, test, type Page, type Route } from "@playwright/test";

import { lowContrastText } from "./contrast-probe";

/**
 * The shared question card (specs/009-orchestration/question-card.md):
 * - the lead's ask_clarification renders as the card, not as Markdown: the
 *   question, 2 to 4 option buttons with the suggested one marked in TEXT,
 *   and a free-text box with Send (QC-09);
 * - keyboard: Tab reaches the options, Enter chooses; the box sends with
 *   Enter and Shift+Enter is a new line (QC-10);
 * - answered and expired states say what happened, in words; the change is
 *   announced (aria-live);
 * - question text is content: shown as plain text, links defanged;
 * - Home's "Waiting on you" lists open questions (QC-11);
 * - AA contrast in both themes; stacked at phone width.
 *
 * NO BACKEND: every API is intercepted with bodies shaped as the backend's.
 */
const THREAD = "99999999-0000-0000-0000-00000000000q";
const SHOTS = process.env.QCARD_SHOTS_DIR;

const send = (route: Route, body: unknown, status = 200) =>
  route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });

function question(over: Record<string, unknown> = {}) {
  return {
    id: "q1",
    thread_id: THREAD,
    asker: { kind: "lead", name: "OmniHarness", tool_call_id: "ask1" },
    origin: "content",
    question: "Which city should I plan Friday's dinner in?",
    context: "Your calendar has two trips that week.",
    options: [
      { label: "Philadelphia", description: "" },
      { label: "New York", description: "" },
      { label: "Boston", description: "" },
    ],
    recommended: 0,
    recommended_label: "Suggested by OmniHarness",
    on_expiry: "stop",
    expires_at: new Date(Date.now() + 23 * 3600_000).toISOString(),
    created_at: new Date().toISOString(),
    state: "open",
    expired_reason: "",
    answer: null,
    outcome: "",
    free_text_max: 2000,
    ...over,
  };
}

const CLARIFICATION =
  "❓ Your calendar has two trips that week.\n\nWhich city should I plan Friday's dinner in?\n\n  1. Philadelphia (suggested)\n  2. New York\n  3. Boston\n\nAnswer on the card, or reply with an option number or your own words.";

async function mockChat(
  page: Page,
  scheme: "light" | "dark",
  questions: unknown[],
  posts: unknown[] = [],
) {
  await page.addInitScript((t) => {
    try {
      localStorage.setItem("theme", t);
    } catch {}
  }, scheme);
  const state = {
    values: {
      title: "Friday dinner",
      messages: [
        { type: "human", id: "h1", content: "plan dinner for Friday" },
        {
          type: "ai",
          id: "a1",
          content: "",
          tool_calls: [
            {
              id: "ask1",
              name: "ask_clarification",
              args: { question: "Which city?" },
            },
          ],
        },
        {
          type: "tool",
          id: "clarification:ask1",
          name: "ask_clarification",
          tool_call_id: "ask1",
          content: CLARIFICATION,
          additional_kwargs: { omniharness_question: { id: "q1" } },
        },
      ],
    },
    next: [],
    tasks: [],
    metadata: {},
    created_at: new Date().toISOString(),
    checkpoint: { thread_id: THREAD, checkpoint_id: "c1", checkpoint_ns: "" },
    parent_checkpoint: null,
  };
  await page.route("**/api/langgraph/**", (route) => {
    const url = route.request().url();
    if (url.includes("/history")) return send(route, [state]);
    if (url.includes("/runs") || url.includes("/search"))
      return send(route, []);
    return send(route, state);
  });
  await page.route("**/api/confirmations", (route) =>
    send(route, { actions: [], readable: true, error: "" }),
  );
  await page.route("**/api/inbox/alerts", (route) =>
    send(route, { alerts: [], waiting_count: 0 }),
  );
  let current = questions;
  await page.route(`**/api/threads/${THREAD}/questions`, (route) =>
    send(route, { questions: current }),
  );
  await page.route("**/api/questions/*/answer", async (route) => {
    const body = route.request().postDataJSON() as {
      option?: number;
      text?: string;
    };
    posts.push(body);
    const answered = question({
      state: "answered",
      answer: {
        option: body.option ?? null,
        text: body.text ?? null,
        via: "button",
        at: new Date().toISOString(),
      },
      outcome: "Answered",
    });
    current = [answered];
    return send(route, { question: answered, resume_run_id: null });
  });
}

async function expectAA(page: Page) {
  const found = await page.evaluate(lowContrastText);
  expect(
    found,
    found
      .map((f) => `${f.ratio}/${f.need} "${f.text}" ${f.color} [${f.cls}]`)
      .join("\n"),
  ).toEqual([]);
}

async function shot(page: Page, name: string, target = "question-card") {
  if (!SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  await page
    .getByTestId(target)
    .first()
    .screenshot({ path: `${SHOTS}/${name}.png` });
}

for (const scheme of ["light", "dark"] as const) {
  test.describe(`${scheme} theme`, () => {
    test.use({ colorScheme: scheme, viewport: { width: 1280, height: 900 } });

    test("an open question: options, the suggestion in words, a text box; AA", async ({
      page,
    }) => {
      await mockChat(page, scheme, [question()]);
      await page.goto(`/workspace/chats/${THREAD}`, {
        waitUntil: "networkidle",
      });
      const card = page.getByTestId("question-card");
      await expect(card).toBeVisible();
      await expect(card).toHaveAttribute("data-state", "open");
      await expect(card).toContainText("OmniHarness asks");
      await expect(page.getByTestId("question-text")).toHaveText(
        "Which city should I plan Friday's dinner in?",
      );
      await expect(page.getByTestId("question-option")).toHaveCount(3);
      await expect(page.getByTestId("question-suggested")).toHaveText(
        "Suggested by OmniHarness",
      );
      await expect(page.getByTestId("question-text-input")).toBeVisible();
      await expect(page.getByTestId("question-time-left")).toContainText(
        "left",
      );
      // Rendered as the card, not as the tool message's Markdown text.
      await expect(page.getByText("Answer on the card, or reply")).toHaveCount(
        0,
      );
      await expectAA(page);
      await shot(page, `open-${scheme}`);
    });

    test("keyboard: Tab to an option and Enter chooses it; the state change is announced", async ({
      page,
    }) => {
      const posts: unknown[] = [];
      await mockChat(page, scheme, [question()], posts);
      await page.goto(`/workspace/chats/${THREAD}`, {
        waitUntil: "networkidle",
      });
      const first = page.getByTestId("question-option").first();
      await first.focus();
      await page.keyboard.press("Tab");
      await expect(page.getByTestId("question-option").nth(1)).toBeFocused();
      await page.keyboard.press("Enter");
      await expect.poll(() => posts).toEqual([{ option: 1 }]);
      const card = page.getByTestId("question-card");
      await expect(card).toHaveAttribute("data-state", "answered");
      await expect(page.getByTestId("question-outcome")).toHaveText(
        "You chose New York, on the card.",
      );
      // The outcome is its own live region, so the change is announced once
      // (no hidden copy repeating it).
      await expect(page.getByTestId("question-outcome")).toHaveAttribute(
        "aria-live",
        "polite",
      );
      await expect(
        page.getByText("You chose New York, on the card."),
      ).toHaveCount(1);
      await expect(page.getByTestId("question-option")).toHaveCount(0);
      await expectAA(page);
      await shot(page, `answered-${scheme}`);
    });

    test("the text box: Shift+Enter is a new line, Enter sends", async ({
      page,
    }) => {
      const posts: unknown[] = [];
      await mockChat(page, scheme, [question()], posts);
      await page.goto(`/workspace/chats/${THREAD}`, {
        waitUntil: "networkidle",
      });
      const box = page.getByTestId("question-text-input");
      await box.click();
      await page.keyboard.type("Chicago");
      await page.keyboard.press("Shift+Enter");
      await page.keyboard.type("near the river");
      await expect(box).toHaveValue("Chicago\nnear the river");
      expect(posts).toEqual([]);
      await page.keyboard.press("Enter");
      await expect
        .poll(() => posts)
        .toEqual([{ text: "Chicago\nnear the river" }]);
      await expect(page.getByTestId("question-outcome")).toContainText(
        "You answered on the card:",
      );
    });

    test("expired: the default applied, in words; nothing to press", async ({
      page,
    }) => {
      await mockChat(page, scheme, [
        question({
          state: "expired",
          expired_reason: "timeout",
          outcome: "No answer by 14:32 UTC; stopped this path.",
        }),
      ]);
      await page.goto(`/workspace/chats/${THREAD}`, {
        waitUntil: "networkidle",
      });
      const card = page.getByTestId("question-card");
      await expect(card).toHaveAttribute("data-state", "expired");
      await expect(page.getByTestId("question-outcome")).toHaveText(
        "No answer by 14:32 UTC; stopped this path.",
      );
      await expect(page.getByTestId("question-option")).toHaveCount(0);
      await expect(page.getByTestId("question-text-input")).toHaveCount(0);
      await expectAA(page);
      await shot(page, `expired-${scheme}`);
    });

    test("Home lists the open question beside the approvals", async ({
      page,
    }) => {
      await page.addInitScript((t) => {
        try {
          localStorage.setItem("theme", t);
        } catch {}
      }, scheme);
      await page.route("**/api/confirmations", (route) =>
        send(route, { actions: [], readable: true, error: "" }),
      );
      await page.route("**/api/inbox/alerts", (route) =>
        send(route, {
          alerts: [],
          waiting_count: 0,
          dismissals_readable: true,
        }),
      );
      await page.route("**/api/questions?state=open", (route) =>
        send(route, {
          questions: [
            question({
              asker: {
                kind: "code_job",
                name: "The coding job",
                tool_call_id: null,
              },
              question: "Keep the old function name as a deprecated alias?",
              context: "",
              options: [
                { label: "Keep an alias", description: "" },
                { label: "Rename everywhere", description: "" },
              ],
              recommended_label: "Suggested by The coding job",
            }),
          ],
        }),
      );
      await page.goto("/workspace/home", { waitUntil: "networkidle" });
      const waiting = page.getByTestId("questions-waiting");
      await expect(waiting).toBeVisible();
      await expect(waiting).toContainText("The coding job asks");
      await expect(waiting).toContainText("Keep an alias");
      await expect(
        waiting.getByRole("link", { name: "Open the chat" }),
      ).toHaveAttribute("href", `/workspace/chats/${THREAD}`);
      await expectAA(page);
      await shot(page, `home-${scheme}`, "waiting-on-you");
    });
  });
}

test("question text is content: plain text, links defanged, never Markdown", async ({
  page,
}) => {
  await mockChat(page, "light", [
    question({
      question:
        "**Bold?** see https://evil.example/x and [click](https://a.example)",
      options: [
        { label: "evil.example", description: "" },
        { label: "Other", description: "" },
      ],
    }),
  ]);
  await page.goto(`/workspace/chats/${THREAD}`, { waitUntil: "networkidle" });
  const text = page.getByTestId("question-text");
  await expect(text).toHaveText(
    "**Bold?** see hxxps://evil[.]example/x and [click](hxxps://a[.]example)",
  );
  await expect(page.getByTestId("question-card").locator("a")).toHaveCount(0);
  await expect(page.getByTestId("question-option").first()).toContainText(
    "evil[.]example",
  );
});

test("phone width: options stack, nothing scrolls sideways", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockChat(page, "light", [question()]);
  await page.goto(`/workspace/chats/${THREAD}`, { waitUntil: "networkidle" });
  const options = page.getByTestId("question-option");
  await expect(options).toHaveCount(3);
  const boxes = await Promise.all(
    [0, 1, 2].map((i) => options.nth(i).boundingBox()),
  );
  expect(boxes[1]!.y).toBeGreaterThan(boxes[0]!.y);
  expect(boxes[2]!.y).toBeGreaterThan(boxes[1]!.y);
  const card = await page.getByTestId("question-card").boundingBox();
  expect(card!.x + card!.width).toBeLessThanOrEqual(390);
  await shot(page, "open-phone");
});

test("a free-form question shows only its text box", async ({ page }) => {
  await mockChat(page, "light", [
    question({
      question: "What is your flight number?",
      context: "",
      options: [],
      recommended: null,
      recommended_label: null,
    }),
  ]);
  await page.goto(`/workspace/chats/${THREAD}`, { waitUntil: "networkidle" });
  await expect(page.getByTestId("question-card")).toBeVisible();
  await expect(page.getByTestId("question-options")).toHaveCount(0);
  await expect(page.getByTestId("question-text-input")).toHaveAttribute(
    "placeholder",
    "Your answer",
  );
  await expectAA(page);
  await shot(page, "free-form-light");
});
