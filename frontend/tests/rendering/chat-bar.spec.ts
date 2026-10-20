import { expect, test, type Page, type Route } from "@playwright/test";

/**
 * Feature 006 chat bar, on the production build, with every API stubbed.
 *
 * The Integrations tab is the existing per-thread tool selection made
 * visible, so the toggle is asserted on the request that leaves the browser
 * (PUT /api/threads/{id}/tools), not on the switch's own state.
 */
const THREAD = "11111111-2222-3333-4444-555555555555";
const AGO = new Date(Date.now() - 5 * 60 * 1000).toISOString();

type Model = {
  name: string;
  supports_thinking?: boolean;
  supports_reasoning_effort?: boolean;
};

const MODELS: Model[] = [
  { name: "sonnet", supports_thinking: true, supports_reasoning_effort: true },
];

const CATALOG = {
  categories: ["Productivity"],
  items: [
    ["local:filesystem", "filesystem", null, true],
    ["local:dead-server", "dead-server", null, false],
    ["local:fresh", "fresh", null, false],
    ["connector:GMAIL", "Gmail", "GMAIL", false],
    ["connector:GOOGLECALENDAR", "Google Calendar", "GOOGLECALENDAR", false],
    ["connector:SLACK", "Slack", "SLACK", false],
  ].map(([tool_id, name, toolkit, pinned]) => ({
    tool_id,
    name,
    description: "",
    source: (tool_id as string).startsWith("connector:")
      ? "connector"
      : "local",
    origin: "builtin",
    toolkit,
    icon: null,
    category: "Productivity",
    connected: true,
    pinned,
  })),
};

const SOURCES = {
  thread_id: THREAD,
  failing: 1,
  connectors_available: true,
  sources: [
    ["local:filesystem", "filesystem", "live", { tool_count: 4 }],
    [
      "local:dead-server",
      "dead-server",
      "unreachable",
      { error: "ConnectError: All connection attempts failed" },
    ],
    ["local:fresh", "fresh", "not-loaded", {}],
    ["connector:GMAIL", "Gmail", "authorised-not-selected", {}],
    [
      "connector:GOOGLECALENDAR",
      "Google Calendar",
      "authorised-selected",
      { last_success_at: AGO },
    ],
    ["connector:SLACK", "Slack", "not-authorised", {}],
  ].map(([id, name, state, extra]) => ({
    id,
    name,
    kind: (id as string).startsWith("connector:") ? "connector" : "local",
    state,
    tool_count: null,
    error: null,
    selected: null,
    ...(extra as object),
  })),
};

const PROJECT = {
  id: "p1",
  name: "OmniHarness",
  why: null,
  status: "active",
  context: null,
  version: 1,
  created_at: AGO,
  updated_at: AGO,
};

interface Seen {
  puts: string[][];
  deletes: string[];
  links: unknown[];
}

const json = (route: Route, body: unknown, status = 200) =>
  route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });

async function stub(
  page: Page,
  { models = MODELS, attached = true } = {},
): Promise<Seen> {
  const seen: Seen = { puts: [], deletes: [], links: [] };
  let selection = ["local:filesystem", "connector:GOOGLECALENDAR"];
  await page.route("**/api/langgraph/**", (route) => {
    const url = route.request().url();
    if (url.includes("/history")) return json(route, []);
    if (url.includes("/runs")) return json(route, []);
    if (url.includes("/threads/search")) return json(route, []);
    return json(route, {
      thread_id: THREAD,
      values: { messages: [] },
      metadata: {},
    });
  });
  await page.route("**/api/models", (route) =>
    json(route, {
      models: models.map((m) => ({
        id: m.name,
        model: `provider/${m.name}`,
        display_name: m.name === "sonnet" ? "Claude Sonnet" : m.name,
        ...m,
      })),
      token_usage: { enabled: false },
    }),
  );
  await page.route("**/api/tools/catalog", (route) => json(route, CATALOG));
  await page.route("**/api/threads/*/tools/count", (route) =>
    json(route, { count: 7, cap: 40, over_cap: false }),
  );
  await page.route("**/api/threads/*/tools", async (route) => {
    if (route.request().method() === "PUT") {
      const body = route.request().postDataJSON() as { sources: string[] };
      seen.puts.push(body.sources);
      selection = Array.from(new Set(["local:filesystem", ...body.sources]));
    }
    return json(route, {
      thread_id: THREAD,
      sources: selection,
      pinned: ["local:filesystem"],
    });
  });
  await page.route("**/api/tool-sources*", (route) => json(route, SOURCES));
  await page.route("**/api/ledger/threads/*/projects", (route) =>
    json(route, attached ? [{ link_id: "l1", project: PROJECT }] : []),
  );
  await page.route("**/api/ledger/projects", (route) =>
    json(route, [
      { ...PROJECT, open_tasks: 1, overdue: 0, done_tasks: 0 },
      {
        ...PROJECT,
        id: "p2",
        name: "Beta launch",
        open_tasks: 0,
        overdue: 0,
        done_tasks: 0,
      },
    ]),
  );
  await page.route("**/api/ledger/links", (route) => {
    seen.links.push(route.request().postDataJSON());
    return json(route, { id: "l2" }, 201);
  });
  await page.route("**/api/ledger/links/*", (route) => {
    seen.deletes.push(route.request().url());
    return route.fulfill({ status: 204 });
  });
  await page.route("**/api/agents", (route) =>
    json(route, {
      agents: [
        {
          name: "researcher",
          description: "Finds sources",
          model: null,
          tool_groups: null,
          skills: null,
        },
        {
          name: "release-manager",
          description: "Ships slices",
          model: null,
          tool_groups: null,
          skills: ["changelog"],
        },
      ],
    }),
  );
  await page.route("**/api/skills", (route) =>
    json(route, {
      skills: [
        {
          name: "changelog",
          description: "",
          category: "",
          license: "",
          enabled: true,
        },
        {
          name: "cite",
          description: "",
          category: "",
          license: "",
          enabled: true,
        },
        {
          name: "off-skill",
          description: "",
          category: "",
          license: "",
          enabled: false,
        },
      ],
    }),
  );
  await page.route("**/api/threads/*/uploads/list", (route) =>
    json(route, { files: [], count: 0 }),
  );
  await page.route("**/api/threads/*/suggestions", (route) =>
    json(route, { suggestions: [] }),
  );
  return seen;
}

const bar = (page: Page) => page.getByTestId("chat-bar");
// The message box is a textbox, and a combobox while a dropdown is open.
const message = (page: Page) => page.getByLabel("Message", { exact: true });

async function openPicker(page: Page) {
  await page.getByRole("button", { name: "Add context" }).click();
  const picker = page.getByRole("dialog", { name: "Add context" });
  await expect(picker).toBeVisible();
  return picker;
}

test("chips show the project, the agent, the integrations, the skills; removing a project detaches it", async ({
  page,
}) => {
  const seen = await stub(page);
  await page.goto(`/workspace/chats/${THREAD}`);
  await expect(bar(page).getByTestId("chip-project")).toHaveText(/OmniHarness/);
  await expect(bar(page).getByTestId("chip-agents")).toHaveAccessibleName(
    "Agents in this chat: Lead agent",
  );
  const stack = bar(page).getByTestId("chip-integrations");
  await expect(
    stack.getByRole("img", { name: "Google Calendar logo" }),
  ).toBeVisible();
  await expect(stack.getByRole("img", { name: "filesystem" })).toBeVisible();
  // Skills are read-only in Phase 1: named, never removable.
  await expect(bar(page).getByTestId("chip-skills")).toHaveAccessibleName(
    "Skills this chat's agent may use: changelog, cite",
  );
  await expect(
    bar(page).getByTestId("chip-skills").getByRole("button"),
  ).toHaveCount(0);

  await page
    .getByRole("button", { name: "Remove project OmniHarness" })
    .click();
  await expect.poll(() => seen.deletes.length).toBe(1);
  expect(seen.deletes[0]).toContain("/api/ledger/links/l1");
});

test("removing an integration chip deselects it for the thread; a pinned one cannot be removed", async ({
  page,
}) => {
  const seen = await stub(page);
  await page.goto(`/workspace/chats/${THREAD}`);
  await page
    .getByRole("button", { name: "Turn off Google Calendar for this chat" })
    .click();
  await expect.poll(() => seen.puts.length).toBe(1);
  expect(seen.puts[0]).not.toContain("connector:GOOGLECALENDAR");
  await expect(
    page.getByRole("button", { name: "Turn off filesystem for this chat" }),
  ).toHaveCount(0);
});

test("the picker is a real tablist: arrow keys move, Esc closes and focus returns to +", async ({
  page,
}) => {
  await stub(page);
  await page.goto(`/workspace/chats/${THREAD}`);
  const picker = await openPicker(page);
  const tablist = picker.getByRole("tablist", { name: "Context type" });
  await expect(tablist.getByRole("tab")).toHaveText([
    "Projects",
    "Agents",
    "Integrations",
    "Skills",
    "Files",
  ]);
  await expect(picker.getByRole("tab", { name: "Integrations" })).toBeFocused();
  await page.keyboard.press("ArrowRight");
  await expect(picker.getByRole("tab", { name: "Skills" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await page.keyboard.press("ArrowLeft");
  await expect(
    picker.getByRole("tab", { name: "Integrations" }),
  ).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("ArrowLeft");
  await expect(picker.getByRole("tab", { name: "Agents" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await page.keyboard.press("Escape");
  await expect(picker).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Add context" })).toBeFocused();
});

test("integrations: status in words, the two-stage connector status, links to MCP Suite, the tool count", async ({
  page,
}) => {
  await stub(page);
  await page.goto(`/workspace/chats/${THREAD}`);
  const picker = await openPicker(page);
  const row = (name: string) =>
    picker.getByRole("listitem").filter({ hasText: name });

  await expect(row("filesystem").getByTestId("integration-status")).toHaveText(
    "Live · 4 tools",
  );
  await expect(row("filesystem")).toContainText("Always on");
  await expect(
    row("Google Calendar").getByTestId("integration-status"),
  ).toHaveText(/^Live · last worked 5 minutes ago$/);
  await expect(row("Gmail").getByTestId("integration-status")).toHaveText(
    "Connected",
  );
  await expect(row("fresh").getByTestId("integration-status")).toHaveText(
    "Not checked yet",
  );
  await expect(row("dead-server").getByTestId("integration-status")).toHaveText(
    "Unreachable",
  );
  await expect(row("dead-server")).toContainText(
    "ConnectError: All connection attempts failed",
  );
  await expect(row("Slack").getByTestId("integration-status")).toHaveText(
    "Not connected",
  );

  // Unreachable and not-connected rows have no switch: a link to MCP Suite.
  for (const [name, label] of [
    ["dead-server", "Check"],
    ["Slack", "Connect"],
  ] as const) {
    await expect(row(name).getByRole("switch")).toHaveCount(0);
    const link = row(name).getByRole("link", { name: new RegExp(label) });
    await expect(link).toHaveAttribute("href", "/workspace/connections");
  }
  await expect(picker.getByTestId("tool-count")).toHaveText(
    "7 / 40 tools for this model",
  );
  await expect(
    row("Slack").getByRole("img", { name: "Slack logo" }),
  ).toBeVisible();
});

test("the integration switch writes the thread's tool selection", async ({
  page,
}) => {
  const seen = await stub(page);
  await page.goto(`/workspace/chats/${THREAD}`);
  const picker = await openPicker(page);
  await picker.getByRole("switch", { name: "Use Gmail in this chat" }).click();
  await expect.poll(() => seen.puts.length).toBe(1);
  expect(seen.puts[0]).toEqual(
    expect.arrayContaining(["connector:GMAIL", "connector:GOOGLECALENDAR"]),
  );
  await expect(
    bar(page)
      .getByTestId("chip-integrations")
      .getByRole("img", { name: "Gmail logo" }),
  ).toBeVisible();
});

test("@ in a new chat: arrows and Enter start the chat with that agent; Esc closes", async ({
  page,
}) => {
  await stub(page);
  await page.goto("/workspace/chats/new");
  await message(page).click();
  await page.keyboard.type("@");
  const list = page.getByRole("listbox");
  await expect(list.getByRole("option")).toHaveCount(2);
  await expect(message(page)).toHaveAttribute("role", "combobox");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("listbox")).toHaveCount(0);

  await page.keyboard.type("r");
  await expect(list.getByRole("option").first()).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await page.keyboard.press("ArrowDown");
  await expect(list.getByRole("option").nth(1)).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await page.keyboard.press("Enter");
  await page.waitForURL("**/workspace/agents/release-manager/chats/new");
});

test("@ in an existing chat lists agents but cannot call one in yet, and says why", async ({
  page,
}) => {
  await stub(page);
  await page.goto(`/workspace/chats/${THREAD}`);
  await message(page).click();
  await page.keyboard.type("@res");
  const option = page.getByRole("option", { name: /researcher/ });
  await expect(option).toHaveAttribute("aria-disabled", "true");
  await expect(option).toContainText("arrives with multi-agent chat");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(new RegExp(`/workspace/chats/${THREAD}$`));
  await expect(message(page)).toHaveValue("@res");
});

test("/ at the start opens the commands; /project opens the picker on Projects", async ({
  page,
}) => {
  const seen = await stub(page);
  await page.goto(`/workspace/chats/${THREAD}`);
  await message(page).click();
  await page.keyboard.type("/");
  await expect(page.getByRole("option")).toHaveText([
    /\/new/,
    /\/project/,
    /\/agent/,
    /\/integrations/,
    /\/skill/,
    /\/attach/,
  ]);
  await page.keyboard.type("pro");
  await page.keyboard.press("Enter");
  const picker = page.getByRole("dialog", { name: "Add context" });
  await expect(picker.getByRole("tab", { name: "Projects" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await expect(message(page)).toHaveValue("");
  await picker.getByRole("button", { name: "Attach to Beta launch" }).click();
  await expect.poll(() => seen.links.length).toBe(1);
  expect(seen.links[0]).toMatchObject({
    project_id: "p2",
    to_kind: "thread",
    to_ref: THREAD,
  });

  // "/" anywhere but the start is just text.
  await page.keyboard.press("Escape");
  await message(page).fill("see a/b");
  await expect(page.getByRole("listbox")).toHaveCount(0);
});

test("attachments still work: the file dialog, a file chip, and removing it", async ({
  page,
}) => {
  await stub(page);
  await page.goto(`/workspace/chats/${THREAD}`);
  const chooser = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "Attach file" }).click();
  await (
    await chooser
  ).setFiles({
    name: "notes.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("hello"),
  });
  await expect(bar(page).getByTestId("chip-file")).toHaveText(/notes\.txt/);
  await page.getByRole("button", { name: "Remove file notes.txt" }).click();
  await expect(bar(page).getByTestId("chip-file")).toHaveCount(0);
});

test("Send is the one primary button; it sends, and is the Stop button while a reply streams", async ({
  page,
}) => {
  await stub(page);
  let release: () => void = () => undefined;
  const sent: string[] = [];
  await page.route("**/api/langgraph/threads/*/runs/stream", async (route) => {
    sent.push(route.request().postData() ?? "");
    await new Promise<void>((r) => (release = r));
    await route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: "",
    });
  });
  await page.goto(`/workspace/chats/${THREAD}`);
  const send = page.getByTestId("send-button");
  await expect(send).toHaveAccessibleName("Send");
  await message(page).fill("hello there");
  await message(page).press("Enter");
  await expect.poll(() => sent.length).toBe(1);
  expect(sent[0]).toContain("hello there");
  await expect(send).toHaveAccessibleName(/Stop|Sending/);
  release();
});

test("reasoning effort shows only when the model supports it and the mode thinks", async ({
  page,
}) => {
  await stub(page, {
    models: [
      {
        name: "plain",
        supports_thinking: true,
        supports_reasoning_effort: false,
      },
    ],
  });
  await page.goto(`/workspace/chats/${THREAD}`);
  await expect(page.getByRole("button", { name: /^Mode: / })).toBeVisible();
  await expect(
    page.getByRole("button", { name: /^Model: plain/ }),
  ).toBeVisible();
  await expect(page.getByTestId("effort-trigger")).toHaveCount(0);
});

test("with a model that supports effort, the control is there in Pro and gone in Flash", async ({
  page,
}) => {
  await stub(page);
  await page.goto(`/workspace/chats/${THREAD}`);
  await expect(page.getByRole("button", { name: "Mode: Pro" })).toBeVisible();
  await expect(page.getByTestId("effort-trigger")).toBeVisible();
  await page.getByRole("button", { name: "Mode: Pro" }).click();
  await page.getByRole("menuitem", { name: /Flash/ }).click();
  await expect(page.getByRole("button", { name: "Mode: Flash" })).toBeVisible();
  await expect(page.getByTestId("effort-trigger")).toHaveCount(0);
});
