import { expect, test, type Page } from "@playwright/test";

import { lowContrastText } from "./contrast-probe";

/**
 * Feature 006: a scheduled run's summary, linked from its Telegram message.
 *
 * - each change the run made on its own, with what it came from;
 * - "Undo all for this run" POSTs the undo and the list shows them undone;
 * - a refusal (409: edited since) is said in words;
 * - AA contrast in both themes.
 *
 * NO BACKEND: /api/studio/runs is intercepted.
 */
const FIRING = "fp-3f9c";

function summary(undone: boolean) {
  return {
    firing_id: FIRING,
    rule_id: "evening-wrap",
    agent: "lead_agent",
    all_undone: undone,
    writes: [
      {
        at: "2026-10-20T22:00:05+00:00",
        tool: "ledger_apply",
        classes: ["tasks"],
        targets: ["Add task “Book the venue” to “Launch”"],
        source_label: "from: email “Lunch Friday”",
        write_id: "w-0000000000000001",
        undone,
      },
      {
        at: "2026-10-20T22:00:09+00:00",
        tool: "ledger_apply",
        classes: ["notes"],
        targets: ["Record decision in Launch: go with plan B"],
        source_label: "from: page “Launch notes”",
        write_id: "w-0000000000000002",
        undone,
      },
    ],
  };
}

async function open(
  page: Page,
  scheme: "light" | "dark",
  undo: { status: number; body: unknown },
) {
  const calls: string[] = [];
  await page.addInitScript((t) => {
    try {
      localStorage.setItem("theme", t);
    } catch {}
  }, scheme);
  await page.route("**/api/studio/runs/**", (route) => {
    const method = route.request().method();
    calls.push(`${method} ${new URL(route.request().url()).pathname}`);
    if (method === "POST")
      return route.fulfill({
        status: undo.status,
        contentType: "application/json",
        body: JSON.stringify(undo.body),
      });
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(summary(false)),
    });
  });
  await page.goto(`/workspace/runs/${FIRING}`, { waitUntil: "networkidle" });
  await expect(page.getByTestId("run-summary")).toBeVisible();
  return calls;
}

for (const scheme of ["dark", "light"] as const) {
  test.describe(`${scheme} theme`, () => {
    test.use({ colorScheme: scheme, viewport: { width: 1280, height: 800 } });

    test("each change names its source, and Undo all reverts the run", async ({
      page,
    }) => {
      const calls = await open(page, scheme, {
        status: 200,
        body: summary(true),
      });
      const writes = page.getByTestId("run-write");
      await expect(writes).toHaveCount(2);
      await expect(writes.nth(0)).toContainText("Book the venue");
      await expect(writes.nth(0)).toContainText("from: email “Lunch Friday”");
      await expect(writes.nth(1)).toContainText("from: page “Launch notes”");
      await page.getByTestId("undo-run").click();
      await expect(page.getByTestId("undo-run-note")).toHaveText(
        "Undone: every change this run made.",
      );
      await expect(page.getByTestId("all-undone")).toBeVisible();
      await expect(page.getByTestId("undo-run")).toHaveCount(0);
      expect(calls).toContain(`POST /api/studio/runs/${FIRING}/undo`);
    });

    test("a refused Undo all says why, and AA contrast holds", async ({
      page,
    }) => {
      await open(page, scheme, {
        status: 409,
        body: {
          detail:
            "something it changed has been edited since, so it was not undone; change it back by hand",
        },
      });
      await page.getByTestId("undo-run").click();
      await expect(page.getByTestId("undo-run-note")).toHaveText(
        "Not undone: something it changed has been edited since, so it was not undone; change it back by hand",
      );
      await expect(page.getByTestId("undo-run")).toBeVisible();
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
