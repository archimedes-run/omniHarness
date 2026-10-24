import { expect, test, type Page } from "@playwright/test";

import { lowContrastText } from "./contrast-probe";

/**
 * 005 FR-009 Amendment 1: a routine ledger write the assistant made from the
 * user's own message is disclosed in the chat with an Undo that reverts it.
 *
 * - the disclosed write's step shows its result and an Undo button;
 * - Undo POSTs /api/ledger/writes/{id}/undo and then says "Undone.";
 * - a refusal (409: edited since) is said in words, and the write stays;
 * - a confirmed write (no write id) has no Undo;
 * - AA contrast in both themes, refusal shown.
 *
 * NO BACKEND: the thread's history and the undo endpoint are intercepted.
 */
const THREAD = "44444444-5555-6666-7777-888888888888";
const WRITE = "w-0123456789abcdef";
const REFUSAL =
  "something it changed has been edited since, so it was not undone; change it back by hand";

function messages(result: string) {
  return [
    {
      type: "human",
      id: "h1",
      content: "add a task to Launch: Draft the summary",
    },
    {
      type: "ai",
      id: "a1",
      content: "",
      tool_calls: [
        {
          id: "c1",
          name: "ledger_apply",
          args: {
            changes: [
              {
                op: "create_task",
                project: "Launch",
                title: "Draft the summary",
              },
            ],
          },
        },
      ],
    },
    {
      type: "tool",
      id: "t1",
      name: "ledger_apply",
      tool_call_id: "c1",
      content: result,
    },
    { type: "ai", id: "a2", content: "Added it to Launch." },
  ];
}

async function open(page: Page, result: string, scheme: "light" | "dark") {
  const json = (body: unknown, status = 200) => ({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
  await page.addInitScript((t) => {
    try {
      localStorage.setItem("theme", t);
    } catch {}
  }, scheme);
  const state = {
    values: { title: "Launch planning", messages: messages(result) },
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
  await page.route("**/api/confirmations", (route) =>
    route.fulfill(json({ actions: [], readable: true, error: "" })),
  );
  await page.route("**/api/inbox/alerts", (route) =>
    route.fulfill(json({ alerts: [], waiting_count: 0 })),
  );
  await page.goto(`/workspace/chats/${THREAD}`, { waitUntil: "networkidle" });
  await expect(page.getByText("Added it to Launch.")).toBeVisible();
}

const disclosed = `Added T-1 “Draft the summary” to Launch. [undo ${WRITE}]`;

for (const scheme of ["dark", "light"] as const) {
  test.describe(`${scheme} theme`, () => {
    test.use({ colorScheme: scheme, viewport: { width: 1440, height: 900 } });

    test("a disclosed write offers Undo, and Undo reverts it through the ledger", async ({
      page,
    }) => {
      const calls: string[] = [];
      await page.route("**/api/ledger/writes/**", (route) => {
        calls.push(
          `${route.request().method()} ${new URL(route.request().url()).pathname}`,
        );
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            write_id: WRITE,
            undone: ["Removed the task “Draft the summary”."],
          }),
        });
      });
      await open(page, disclosed, scheme);
      await expect(
        page.getByText("Added T-1 “Draft the summary” to Launch."),
      ).toBeVisible();
      await expect(page.getByText(`[undo ${WRITE}]`)).toHaveCount(0);
      const undo = page.getByTestId("ledger-undo");
      await expect(undo).toHaveText("Undo");
      await undo.click();
      await expect(page.getByTestId("ledger-undone")).toHaveText("Undone.");
      await expect(undo).toHaveCount(0);
      expect(calls).toEqual([`POST /api/ledger/writes/${WRITE}/undo`]);
    });

    test("a refused Undo says why in words, and AA contrast holds", async ({
      page,
    }) => {
      await page.route("**/api/ledger/writes/**", (route) =>
        route.fulfill({
          status: 409,
          contentType: "application/json",
          body: JSON.stringify({ detail: REFUSAL }),
        }),
      );
      await open(page, disclosed, scheme);
      await page.getByTestId("ledger-undo").click();
      await expect(
        page.getByRole("alert").filter({ hasText: "Not undone" }),
      ).toHaveText(`Not undone: ${REFUSAL}`);
      await expect(page.getByTestId("ledger-undone")).toHaveCount(0);
      const found = await page.evaluate(lowContrastText);
      expect(
        found,
        found
          .map((f) => `${f.ratio}/${f.need} "${f.text}" ${f.color} [${f.cls}]`)
          .join("\n"),
      ).toEqual([]);
    });

    test("a confirmed write has no Undo", async ({ page }) => {
      await open(page, "Added T-1 “Draft the summary” to Launch.", scheme);
      await expect(
        page.getByText("Added T-1 “Draft the summary” to Launch."),
      ).toBeVisible();
      await expect(page.getByTestId("ledger-undo")).toHaveCount(0);
    });
  });
}
