import { expect, test, type Page } from "@playwright/test";

import { lowContrastText } from "./contrast-probe";

/**
 * Feature 007, web research, as rendered:
 *
 * - a search step shows its results as a tidy list (title as an ordinary
 *   link, the site, one line of snippet), never as raw JSON, and nothing is
 *   fetched from the results: no image, no preview, no request to any host
 *   they name;
 * - a turn's outbound calls waiting for the person are ONE card, listing each
 *   call, with "Apply all" (the apply-all route) and a Decline per call;
 * - both read at WCAG AA in both themes.
 *
 * NO BACKEND: the thread's history and the pending set are intercepted.
 * Set WEB_RESEARCH_SHOTS=<dir> to save screenshots.
 */
const THREAD = "77777777-8888-9999-aaaa-bbbbbbbbbbbb";
const HOUR = 60 * 60 * 1000;
const SHOTS = process.env.WEB_RESEARCH_SHOTS;

const SEARCH = JSON.stringify({
  query: "date night restaurants philly",
  results: [
    {
      title: "Vetri Cucina: an intimate Italian tasting menu",
      url: "https://vetri.example/philly",
      snippet:
        "Chef Marc Vetri's flagship. Seasonal pasta, a quiet room, book weeks ahead.",
    },
    {
      title: "Zahav",
      url: "https://zahav.example/",
      snippet:
        "Modern Israeli cooking in Society Hill; the tasting menu is a date-night classic.",
    },
    {
      title: "Laurel",
      url: "https://laurel.example/menu",
      snippet: "Small French-American tasting room on East Passyunk.",
    },
    {
      title: "Not a link",
      url: "javascript:fetch('https://attacker.example/js')",
      snippet: "should never be clickable",
    },
  ],
});

const IMAGES = JSON.stringify({
  query: "candlelit dinner",
  results: [
    {
      title: "Candles on a table",
      url: "",
      image_url: "https://attacker.example/pixel.png?d=secret",
    },
  ],
});

function history() {
  return [
    {
      values: {
        title: "Date night",
        messages: [
          {
            type: "human",
            id: "h1",
            content: "Find 5 great date-night restaurants in Philly with links",
          },
          {
            type: "ai",
            id: "a1",
            content: "",
            tool_calls: [
              {
                id: "s1",
                name: "web_search",
                args: { query: "date night restaurants philly" },
              },
            ],
          },
          {
            type: "tool",
            id: "t1",
            tool_call_id: "s1",
            name: "web_search",
            content: SEARCH,
          },
          { type: "ai", id: "a2", content: "Here are three to start with." },
          { type: "human", id: "h2", content: "And a picture for the invite?" },
          {
            type: "ai",
            id: "a3",
            content: "",
            tool_calls: [
              {
                id: "i1",
                name: "image_search",
                args: { query: "candlelit dinner" },
              },
            ],
          },
          {
            type: "tool",
            id: "t2",
            tool_call_id: "i1",
            name: "image_search",
            content: IMAGES,
          },
          { type: "ai", id: "a4", content: "Found one." },
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

function outbound(id: string, tool: string, args: Record<string, string>) {
  return {
    id,
    tool_name: tool,
    plan_text: `Before I do this, please confirm. I intend to use **${tool}**.`,
    targets: [`${tool}(${JSON.stringify(args)})`],
    requester: "lead_agent",
    delegation_chain: [],
    expires_at: new Date(Date.now() + 4 * HOUR).toISOString(),
    thread_id: THREAD,
    threshold_targets: 10,
    requires_typed_count: false,
    withheld: false,
    origin: "content",
    origin_source: "gmail_read_email",
    origin_label: "Suggested by content from gmail_read_email",
    confirmable_by_typing: false,
    arguments_display: args,
    outbound: true,
    group: "g-turn-1",
  };
}

async function open(
  page: Page,
  theme: "light" | "dark",
  actions: unknown[] = [],
) {
  const json = (body: unknown) => ({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
  const leaked: string[] = [];
  const posted: { url: string; body: string }[] = [];
  // Any request to a host a result names is a zero-click fetch: recorded
  // and aborted, so nothing leaves the machine.
  await page.route(/(attacker|vetri|zahav|laurel)\.example/, (route) => {
    leaked.push(route.request().url());
    return route.abort();
  });
  await page.emulateMedia({ colorScheme: theme });
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.addInitScript((t) => {
    try {
      window.localStorage.setItem("theme", t);
    } catch {}
  }, theme);
  const states = history();
  await page.route("**/api/langgraph/**", (route) => {
    const url = route.request().url();
    if (url.includes("/history")) return route.fulfill(json(states));
    if (url.includes("/runs") || url.includes("/search"))
      return route.fulfill(json([]));
    return route.fulfill(json(states[0]));
  });
  await page.route("**/api/inbox/alerts", (route) =>
    route.fulfill(json({ alerts: [], waiting_count: 0 })),
  );
  await page.route("**/api/confirmations", (route) =>
    route.fulfill(json({ actions, readable: true, error: "" })),
  );
  await page.route("**/api/confirmations/**", (route) => {
    const url = route.request().url();
    posted.push({ url, body: route.request().postData() ?? "" });
    if (url.endsWith("/apply-all")) {
      const ids = JSON.parse(route.request().postData() ?? "{}")
        .ids as string[];
      return route.fulfill(
        json({
          write_id: null,
          results: ids.map((id) => ({
            outcome: "executed",
            action_id: id,
            message: "Done.",
            detail: {},
          })),
          resume_run_id: null,
        }),
      );
    }
    const id = url.split("/").at(-2);
    return route.fulfill(
      json({
        outcome: "declined",
        action_id: id,
        message: "Understood — I have not done it.",
        detail: {},
      }),
    );
  });
  await page.goto(`/workspace/chats/${THREAD}`, { waitUntil: "networkidle" });
  await expect(page.getByText("Here are three to start with.")).toBeVisible();
  return { leaked, posted };
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

for (const theme of ["light", "dark"] as const) {
  test(`${theme}: search results are a list of links, never raw JSON, and nothing is fetched`, async ({
    page,
  }) => {
    const { leaked } = await open(page, theme);
    const lists = page.getByTestId("search-results");
    await expect(lists).toHaveCount(2);
    const rows = lists.first().getByTestId("search-result");
    await expect(rows).toHaveCount(4);
    const link = rows.first().getByRole("link", {
      name: "Vetri Cucina: an intimate Italian tasting menu",
    });
    await expect(link).toHaveAttribute("href", "https://vetri.example/philly");
    await expect(link).toHaveAttribute("target", "_blank");
    await expect(link).toHaveAttribute("rel", /noopener/);
    await expect(link).toHaveAttribute("rel", /noreferrer/);
    await expect(rows.first()).toContainText("vetri[.]example");
    await expect(rows.first()).toContainText("Seasonal pasta");
    // A javascript: URL is never a link.
    await expect(rows.nth(3).getByRole("link")).toHaveCount(0);
    await expect(page.locator('a[href^="javascript:"]')).toHaveCount(0);
    // Every link a result made is http(s).
    for (const href of await page
      .getByTestId("search-result")
      .locator("a")
      .evaluateAll((as) => as.map((a) => a.getAttribute("href") ?? ""))) {
      expect(href).toMatch(/^https?:\/\//);
    }
    // No raw JSON on screen.
    const text = await page.locator("body").innerText();
    expect(text).not.toContain('"results"');
    expect(text).not.toContain('{"');
    expect(text).not.toContain('"snippet"');
    // No image or preload from result data, and no request to their hosts.
    await expect(
      page.locator(
        'img[src*=".example"], link[rel="preload"][href*=".example"], iframe',
      ),
    ).toHaveCount(0);
    await page.waitForTimeout(500);
    expect(leaked, "requests to hosts the results name").toEqual([]);
    await noLowContrast(page);
    if (SHOTS) {
      await lists
        .first()
        .evaluate((el) => el.scrollIntoView({ block: "center" }));
      await page.waitForTimeout(300);
      await page.screenshot({
        path: `${SHOTS}/compact-results-${theme}.png`,
        fullPage: false,
      });
    }
  });

  test(`${theme}: a turn's outbound calls are one card with Apply all and a decline per call`, async ({
    page,
  }) => {
    const actions = [
      outbound("w-search", "web_search", { query: "date night philly" }),
      outbound("w-fetch1", "web_fetch", {
        url: "https://vetri.example/philly",
      }),
      outbound("w-fetch2", "web_fetch", { url: "https://zahav.example/" }),
    ];
    const { posted, leaked } = await open(page, theme, actions);
    const group = page.getByTestId("outbound-group");
    await expect(group).toHaveCount(1);
    await expect(page.getByTestId("pending-action")).toHaveCount(0);
    await expect(group.getByTestId("outbound-call")).toHaveCount(3);
    await expect(group).toContainText("3 outside lookups");
    await expect(group).toContainText(
      "Suggested by content from gmail_read_email",
    );
    await expect(group.getByTestId("outbound-apply-all")).toHaveText(
      "Apply all 3",
    );
    await noLowContrast(page);
    if (SHOTS) {
      await group.scrollIntoViewIfNeeded();
      await group.screenshot({ path: `${SHOTS}/grouped-card-${theme}.png` });
    }

    // Decline one: only that card's decline route.
    await group
      .locator('[data-action-id="w-fetch1"]')
      .getByTestId("outbound-decline")
      .click();
    await expect
      .poll(() => posted.map((p) => p.url))
      .toEqual([
        expect.stringContaining("/api/confirmations/w-fetch1/decline"),
      ]);
    await expect(group.locator('[data-action-id="w-fetch1"]')).toHaveAttribute(
      "data-outcome",
      "declined",
    );
    await expect(group.getByTestId("outbound-apply-all")).toHaveText(
      "Apply all 2",
    );

    // Apply the rest: one apply-all call naming exactly the other two.
    await group.getByTestId("outbound-apply-all").click();
    await expect.poll(() => posted.length).toBe(2);
    expect(posted[1]!.url).toContain("/api/confirmations/apply-all");
    expect(JSON.parse(posted[1]!.body).ids).toEqual(["w-search", "w-fetch2"]);
    await expect(group.getByTestId("outbound-apply-all")).toHaveCount(0);
    await expect(group.locator('[data-action-id="w-fetch2"]')).toHaveAttribute(
      "data-outcome",
      "executed",
    );
    expect(leaked).toEqual([]);
  });
}
