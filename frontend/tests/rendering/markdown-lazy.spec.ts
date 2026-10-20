import { expect, test, type Page } from "@playwright/test";

/**
 * Phase 2.6: code highlighting (shiki) and math (katex) load only when a
 * message needs them. A plain message loads neither; a message with a code
 * fence and math loads both, and both are actually used to render it.
 *
 * NO BACKEND: the thread's history is intercepted.
 */
const THREAD = "22222222-3333-4444-5555-666666666666";

function history(text: string) {
  return [
    {
      values: {
        title: "Lazy markdown",
        messages: [
          { type: "human", id: "h1", content: "Show me" },
          { type: "ai", id: "a1", content: text },
        ],
      },
      next: [],
      tasks: [],
      metadata: {},
      created_at: new Date().toISOString(),
      checkpoint: { thread_id: THREAD, checkpoint_id: "c1", checkpoint_ns: "" },
      parent_checkpoint: null,
    },
  ];
}

/** Open a thread whose last message is `text`; the script files it loaded. */
async function open(page: Page, text: string | null): Promise<Set<string>> {
  const json = (body: unknown) => ({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
  const scripts = new Set<string>();
  page.on("request", (r) => {
    if (r.resourceType() === "script") scripts.add(new URL(r.url()).pathname);
  });
  const states = text === null ? [] : history(text);
  await page.route("**/api/langgraph/**", (route) => {
    const url = route.request().url();
    if (url.includes("/history")) return route.fulfill(json(states));
    if (url.includes("/runs") || url.includes("/search"))
      return route.fulfill(json([]));
    return route.fulfill(
      json(states[0] ?? { thread_id: THREAD, values: { messages: [] } }),
    );
  });
  await page.route("**/api/confirmations", (route) =>
    route.fulfill(json({ actions: [], readable: true, error: "" })),
  );
  await page.route("**/api/inbox/alerts", (route) =>
    route.fulfill(json({ alerts: [], waiting_count: 0 })),
  );
  await page.goto(`/workspace/chats/${THREAD}`, { waitUntil: "networkidle" });
  if (text !== null) await expect(page.getByText("Show me")).toBeVisible();
  await page.waitForTimeout(1500);
  return scripts;
}

const extra = (a: Set<string>, b: Set<string>) =>
  [...a].filter((x) => !b.has(x));

test("a plain message loads nothing beyond an empty thread, and draws no math or highlighting", async ({
  browser,
}) => {
  const empty = await open(await browser.newPage(), null);
  const page = await browser.newPage();
  const plain = await open(page, "Just words, and a price of $5 or $10.");

  expect(extra(plain, empty)).toEqual([]);
  await expect(page.locator(".katex")).toHaveCount(0);
  await expect(page.locator("pre")).toHaveCount(0);
});

test("a message with a code fence and math loads the plugins, and renders with them", async ({
  browser,
}) => {
  const empty = await open(await browser.newPage(), null);
  const page = await browser.newPage();
  const rich = await open(
    page,
    "Here:\n\n```python\nprint('hello')\n```\n\nand the area is $\\pi r^2$.",
  );

  expect(extra(rich, empty).length, "no extra code was loaded").toBeGreaterThan(
    0,
  );
  await expect(page.locator(".katex").first()).toBeVisible();
  // Highlighted: the code is split into coloured token spans.
  await expect
    .poll(() => page.locator("pre code span").count())
    .toBeGreaterThan(2);
});
