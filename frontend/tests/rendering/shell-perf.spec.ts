import { expect, test, type Page } from "@playwright/test";

/**
 * Feature 006 budgets, measured on the production build this suite serves:
 *  - a capsule panel opens in under 150 ms, its content included, cold (its
 *    code not yet fetched) and warm;
 *  - a workspace page is usable in under 1 s: from navigation start until a
 *    click on the capsule opens a panel (the page is hydrated and responds).
 *
 * The numbers are printed (and attached as annotations) so a run records them.
 */
const json = (body: unknown) => ({
  status: 200,
  contentType: "application/json",
  body: JSON.stringify(body),
});

async function stub(page: Page) {
  await page.route("**/api/agents", (route) =>
    route.fulfill(
      json({
        agents: [
          {
            name: "perf-agent",
            description: "",
            model: null,
            tool_groups: null,
            skills: null,
          },
        ],
      }),
    ),
  );
  await page.route("**/threads/search", (route) => route.fulfill(json([])));
}

function record(name: string, ms: number) {
  const value = `${ms.toFixed(1)} ms`;
  test.info().annotations.push({ type: name, description: value });
  console.log(`[perf] ${name}: ${value}`);
}

/** Click a capsule button inside the page and time until the sheet is in the
 * DOM, and until the panel's content is. */
const OPEN = `async ([id, text]) => {
  const t0 = performance.now();
  document.querySelector('[data-capsule="' + id + '"]').click();
  const until = (check) => new Promise((resolve) => {
    const tick = () => (check() ? resolve(performance.now() - t0) : requestAnimationFrame(tick));
    tick();
  });
  const sheet = await until(() => document.querySelector('[data-testid="panel-sheet"]'));
  const code = await until(() =>
    document.querySelector('[data-testid="panel-sheet"]') &&
    !document.querySelector('[data-testid="panel-loading"]'));
  const content = await until(() =>
    document.querySelector('[data-testid="panel-sheet"]')?.textContent?.includes(text));
  return { sheet, code, content };
}`;

test("a capsule panel opens in under 150 ms, cold and warm", async ({
  page,
}) => {
  await stub(page);
  await page.goto("/workspace/chats", { waitUntil: "networkidle" });

  const cold = await page.evaluate<{
    sheet: number;
    code: number;
    content: number;
  }>(`(${OPEN})(["agents", "perf-agent"])`);
  record("panel open, cold (sheet)", cold.sheet);
  record("panel open, cold (code loaded)", cold.code);
  record("panel open, cold (content)", cold.content);
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("panel-sheet")).toHaveCount(0);

  const warm = await page.evaluate<{
    sheet: number;
    code: number;
    content: number;
  }>(`(${OPEN})(["agents", "perf-agent"])`);
  record("panel open, warm (sheet)", warm.sheet);
  record("panel open, warm (content)", warm.content);

  expect(cold.sheet).toBeLessThan(150);
  expect(cold.content).toBeLessThan(150);
  expect(warm.sheet).toBeLessThan(150);
  expect(warm.content).toBeLessThan(150);
});

for (const path of ["/workspace/chats", "/workspace/home"]) {
  test(`${path} is usable in under 1 s`, async ({ page }) => {
    await stub(page);
    // From the first script on, try the capsule every frame until a click
    // opens a panel: that is when the page responds.
    await page.addInitScript(() => {
      const w = window as unknown as { __usable?: number };
      const tick = () => {
        if (document.querySelector('[data-testid="panel-sheet"]')) {
          w.__usable = performance.now();
          return;
        }
        document.querySelector<HTMLElement>('[data-capsule="tasks"]')?.click();
        setTimeout(tick, 10);
      };
      tick();
    });
    await page.goto(path, { waitUntil: "commit" });
    await page.waitForFunction(
      () => (window as unknown as { __usable?: number }).__usable,
    );
    const usable = await page.evaluate(
      () => (window as unknown as { __usable: number }).__usable,
    );
    record(`${path} usable`, usable);
    expect(usable).toBeLessThan(1000);
  });
}
