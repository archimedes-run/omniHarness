import { expect, test } from "@playwright/test";

import { lowContrastText } from "./contrast-probe";

/**
 * The chat bar in both themes (Feature 006): the bar, its chips, and the "+"
 * picker open on Integrations, where the status words carry colour. Uses the
 * same probe as contrast.spec.ts, kept separate so the two specs do not
 * collide while that file is edited elsewhere.
 */
const THREAD = "11111111-2222-3333-4444-555555555555";
const AGO = new Date(Date.now() - 5 * 60 * 1000).toISOString();

const ROUTES: Record<string, unknown> = {
  "**/api/models": {
    models: [
      {
        id: "sonnet",
        name: "sonnet",
        model: "provider/sonnet",
        display_name: "Claude Sonnet",
        supports_thinking: true,
        supports_reasoning_effort: true,
      },
    ],
    token_usage: { enabled: false },
  },
  "**/api/tools/catalog": {
    categories: [],
    items: [
      ["local:filesystem", "filesystem", null],
      ["local:dead", "dead", null],
      ["connector:GMAIL", "Gmail", "GMAIL"],
      ["connector:GOOGLECALENDAR", "Google Calendar", "GOOGLECALENDAR"],
      ["connector:SLACK", "Slack", "SLACK"],
    ].map(([tool_id, name, toolkit]) => ({
      tool_id,
      name,
      description: "",
      source: tool_id!.startsWith("connector") ? "connector" : "local",
      origin: "builtin",
      toolkit,
      icon: null,
      category: "",
      connected: true,
      pinned: tool_id === "local:filesystem",
    })),
  },
  "**/api/threads/*/tools/count": { count: 7, cap: 40, over_cap: false },
  "**/api/threads/*/tools": {
    thread_id: THREAD,
    sources: ["local:filesystem", "connector:GOOGLECALENDAR"],
    pinned: ["local:filesystem"],
  },
  "**/api/tool-sources*": {
    thread_id: THREAD,
    failing: 1,
    connectors_available: true,
    sources: [
      ["local:filesystem", "live", { tool_count: 4 }],
      ["local:dead", "unreachable", { error: "ConnectError: refused" }],
      ["connector:GMAIL", "authorised", {}],
      [
        "connector:GOOGLECALENDAR",
        "authorised-selected",
        { last_success_at: AGO },
      ],
      ["connector:SLACK", "not-authorised", {}],
    ].map(([id, state, extra]) => ({
      id,
      name: (id as string).split(":")[1],
      kind: (id as string).startsWith("connector") ? "connector" : "local",
      state,
      tool_count: null,
      error: null,
      selected: null,
      ...(extra as object),
    })),
  },
  "**/api/ledger/threads/*/projects": [
    {
      link_id: "l1",
      project: { id: "p1", name: "OmniHarness", status: "active", version: 1 },
    },
  ],
  "**/api/ledger/projects": [],
  "**/api/agents": { agents: [] },
  "**/api/skills": {
    skills: [
      {
        name: "cite",
        description: "",
        category: "",
        license: "",
        enabled: true,
      },
    ],
  },
};

for (const scheme of ["light", "dark"] as const) {
  test(`${scheme}: the chat bar and its picker meet WCAG AA`, async ({
    page,
  }) => {
    await page.emulateMedia({ colorScheme: scheme });
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.addInitScript((t) => {
      try {
        localStorage.setItem("theme", t);
      } catch {}
    }, scheme);
    await page.route("**/api/langgraph/**", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(
          route.request().url().includes("/history") ||
            route.request().url().includes("/runs") ||
            route.request().url().includes("/search")
            ? []
            : { thread_id: THREAD, values: { messages: [] }, metadata: {} },
        ),
      }),
    );
    for (const [pattern, body] of Object.entries(ROUTES)) {
      await page.route(pattern, (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(body),
        }),
      );
    }
    await page.goto(`/workspace/chats/${THREAD}`, { waitUntil: "networkidle" });
    expect(
      await page.evaluate(() =>
        document.documentElement.classList.contains("dark"),
      ),
    ).toBe(scheme === "dark");
    await expect(page.getByTestId("chip-project")).toBeVisible();
    await page.getByRole("button", { name: "Add context" }).click();
    await expect(page.getByTestId("integration-status").first()).toBeVisible();
    await page.waitForTimeout(400);

    const found = await page.evaluate(lowContrastText);
    expect(
      found,
      found
        .map((f) => `${f.ratio}/${f.need} "${f.text}" ${f.color} [${f.cls}]`)
        .join("\n"),
    ).toEqual([]);
  });
}
