import { expect, type Page, type Route } from "@playwright/test";

/**
 * The chat bar's API, stubbed (chat-bar.spec.ts, chat-bar-v2.spec.ts and
 * chat-bar-contrast.spec.ts). Writes are recorded as the request that left
 * the browser, so a test asserts what the gateway was asked to do.
 */
export const THREAD = "11111111-2222-3333-4444-555555555555";
const AGO = new Date(Date.now() - 5 * 60 * 1000).toISOString();

export type Model = {
  name: string;
  supports_thinking?: boolean;
  supports_reasoning_effort?: boolean;
};

export const MODELS: Model[] = [
  { name: "sonnet", supports_thinking: true, supports_reasoning_effort: true },
];

type Src = [
  id: string,
  name: string,
  toolkit: string | null,
  pinned: boolean,
  state: string,
  extra?: object,
];

const BASE_SOURCES: Src[] = [
  ["local:filesystem", "filesystem", null, true, "live", { tool_count: 4 }],
  [
    "local:dead-server",
    "dead-server",
    null,
    false,
    "unreachable",
    { error: "ConnectError: All connection attempts failed" },
  ],
  ["local:fresh", "fresh", null, false, "not-loaded"],
  ["connector:GMAIL", "Gmail", "GMAIL", false, "authorised-not-selected"],
  [
    "connector:GOOGLECALENDAR",
    "Google Calendar",
    "GOOGLECALENDAR",
    false,
    "authorised-selected",
    { last_success_at: AGO },
  ],
  ["connector:SLACK", "Slack", "SLACK", false, "not-authorised"],
];

/** Four more live local servers, for the integrations overflow. */
export const MORE_SOURCES: Src[] = ["alpha", "bravo", "charlie", "delta"].map(
  (n) => [`local:${n}`, n, null, false, "live", { tool_count: 2 }],
);

const skill = (name: string, enabled = true) => ({
  name,
  description: "",
  category: "",
  license: "",
  enabled,
});

export const BASE_SKILLS = ["changelog", "cite"];
/** Enough skills for "+N skills". */
export const MANY_SKILLS = [
  "changelog",
  "cite",
  "deep-research",
  "spec-kit",
  "chart",
  "summarise",
];

export interface Seen {
  puts: string[][];
  skillPuts: string[][];
  deletes: string[];
  links: unknown[];
  sent: string[];
}

export const json = (route: Route, body: unknown, status = 200) =>
  route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });

export interface StubOptions {
  models?: Model[];
  attached?: boolean;
  skills?: string[];
  selection?: string[];
  extraSources?: Src[];
  excluded?: string[];
  /** Null: the preferences cannot be read. */
  displayName?: string | null;
  skillsFail?: boolean;
}

export async function stub(
  page: Page,
  {
    models = MODELS,
    attached = true,
    skills = BASE_SKILLS,
    selection: initialSelection = [
      "local:filesystem",
      "connector:GOOGLECALENDAR",
    ],
    extraSources = [] as Src[],
    excluded: initialExcluded = [] as string[],
    displayName = "Rishabh",
    skillsFail = false,
  }: StubOptions = {},
): Promise<Seen> {
  const seen: Seen = {
    puts: [],
    skillPuts: [],
    deletes: [],
    links: [],
    sent: [],
  };
  const all = [...BASE_SOURCES, ...extraSources];
  let selection = initialSelection;
  let excluded = initialExcluded;
  await page.route("**/api/langgraph/**", (route) => {
    const url = route.request().url();
    if (url.includes("/runs/stream")) {
      seen.sent.push(route.request().postData() ?? "");
      return route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: "",
      });
    }
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
  await page.route("**/api/tools/catalog", (route) =>
    json(route, {
      categories: ["Productivity"],
      items: all.map(([tool_id, name, toolkit, pinned]) => ({
        tool_id,
        name,
        description: "",
        source: tool_id.startsWith("connector:") ? "connector" : "local",
        origin: "builtin",
        toolkit,
        icon: null,
        category: "Productivity",
        connected: true,
        pinned,
      })),
    }),
  );
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
  await page.route("**/api/threads/*/skills", async (route) => {
    if (skillsFail) return json(route, { detail: "down" }, 503);
    if (route.request().method() === "PUT") {
      const body = route.request().postDataJSON() as { excluded: string[] };
      seen.skillPuts.push(body.excluded);
      excluded = body.excluded;
    }
    return json(route, { thread_id: THREAD, excluded });
  });
  await page.route("**/api/tool-sources*", (route) =>
    json(route, {
      thread_id: THREAD,
      failing: all.filter((s) => s[4] === "unreachable").length,
      connectors_available: true,
      sources: all.map(([id, name, , , state, extra]) => ({
        id,
        name,
        kind: id.startsWith("connector:") ? "connector" : "local",
        state,
        tool_count: null,
        error: null,
        selected: null,
        ...(extra ?? {}),
      })),
    }),
  );
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
  await page.route("**/api/agents/*", (route) =>
    json(route, {
      name: route.request().url().split("/").pop(),
      description: "",
      model: null,
      tool_groups: null,
      skills: null,
    }),
  );
  await page.route("**/api/skills", (route) =>
    json(route, {
      skills: [...skills.map((s) => skill(s)), skill("off-skill", false)],
    }),
  );
  await page.route("**/api/threads/*/uploads/list", (route) =>
    json(route, { files: [], count: 0 }),
  );
  await page.route("**/api/threads/*/suggestions", (route) =>
    json(route, { suggestions: [] }),
  );
  await page.route("**/api/preferences", (route) =>
    displayName === null
      ? json(route, { detail: "down" }, 503)
      : json(route, {
          appearance: "system",
          appearance_chosen: false,
          display_name: displayName,
          display_name_effective: displayName,
        }),
  );
  return seen;
}

export const bar = (page: Page) => page.getByTestId("chat-bar");
// The message box is a textbox, and a combobox while a dropdown is open.
export const message = (page: Page) =>
  page.getByLabel("Message", { exact: true });

export async function openPicker(page: Page) {
  await page.getByRole("button", { name: "Add context" }).click();
  const picker = page.getByRole("dialog", { name: "Add context" });
  await expect(picker).toBeVisible();
  return picker;
}

/** A chip by its kind and name. */
export const chip = (page: Page, kind: string, name: string) =>
  bar(page).getByTestId(`chip-${kind}`).filter({ hasText: name });

/** Eight-plus pieces of context: overflow in both groups, one unreachable. */
export const EIGHT_PLUS = {
  skills: MANY_SKILLS,
  extraSources: MORE_SOURCES,
  selection: [
    "local:filesystem",
    "connector:GOOGLECALENDAR",
    "local:dead-server",
    "local:alpha",
    "local:bravo",
    "local:charlie",
    "local:delta",
  ],
};
