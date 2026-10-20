import { expect, test, type Page } from "@playwright/test";

import { lowContrastText } from "./contrast-probe";
import { stubAutomations, stubTasks } from "./tasks-automations-stubs";

/**
 * Feature 006 Tasks and Automations panels: every state they draw meets WCAG
 * AA in both themes (the panels open over a page, so contrast.spec.ts's page
 * list does not reach them), and each opens in under 150 ms.
 */
const STATES: [string, (page: Page) => Promise<void>][] = [
  [
    "automations history",
    async (page) => {
      await page.goto("/workspace/chats?panel=automations");
      await page.getByTestId("run").first().waitFor();
    },
  ],
  [
    "automations edit",
    async (page) => {
      await page.goto("/workspace/chats?panel=automations");
      await page.getByRole("tab", { name: "Edit" }).click();
      await page.getByTestId("rule-form").waitFor();
    },
  ],
  [
    "automations new",
    async (page) => {
      await page.goto("/workspace/chats?panel=automations");
      await page.getByTestId("new-automation").click();
      await page.getByTestId("new-automation-editor").waitFor();
    },
  ],
  [
    "tasks",
    async (page) => {
      await page.goto("/workspace/chats?panel=tasks");
      await page.getByTestId("task").first().waitFor();
    },
  ],
  [
    "tasks decisions",
    async (page) => {
      await page.goto("/workspace/chats?panel=tasks");
      await page.getByRole("tab", { name: "Decisions" }).click();
    },
  ],
];

for (const scheme of ["light", "dark"] as const) {
  test.describe(`${scheme} theme`, () => {
    test.use({ colorScheme: scheme, viewport: { width: 1440, height: 900 } });
    for (const [name, open] of STATES) {
      test(`${name}: all text meets WCAG AA`, async ({ page }) => {
        await page.addInitScript((t) => {
          try {
            localStorage.setItem("theme", t);
          } catch {}
        }, scheme);
        await stubAutomations(page);
        await stubTasks(page);
        await open(page);
        await page.waitForTimeout(400);
        const found = await page.evaluate(lowContrastText);
        const inPanel = found.filter((f) => f.text.length > 0);
        expect(
          inPanel,
          inPanel
            .map((f) => `${f.ratio}/${f.need} "${f.text}" ${f.color}`)
            .join("\n"),
        ).toEqual([]);
      });
    }
  });
}

const OPEN = `async ([id, text]) => {
  const t0 = performance.now();
  document.querySelector('[data-capsule="' + id + '"]').click();
  const until = (check) => new Promise((resolve) => {
    const tick = () => (check() ? resolve(performance.now() - t0) : requestAnimationFrame(tick));
    tick();
  });
  return until(() =>
    document.querySelector('[data-testid="panel-sheet"]')?.textContent?.includes(text));
}`;

for (const [id, text] of [
  ["automations", "New automation"],
  ["tasks", "New project"],
] as const) {
  test(`the ${id} panel opens in under 150 ms`, async ({ page }) => {
    await stubAutomations(page);
    await stubTasks(page);
    await page.goto("/workspace/chats", { waitUntil: "networkidle" });
    const ms = await page.evaluate<number>(`(${OPEN})(["${id}", "${text}"])`);
    console.log(`[perf] ${id} panel open (cold, content): ${ms.toFixed(1)} ms`);
    expect(ms).toBeLessThan(150);
  });
}
