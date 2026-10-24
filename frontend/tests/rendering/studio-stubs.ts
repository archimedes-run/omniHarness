import type { Page } from "@playwright/test";

import { json, stub as chatBarStub } from "./chat-bar-stubs";
import { ruleFile, type ScheduleRule } from "./schedule-stubs";

/**
 * The Agent & Skill Studio (006-G) against a STATEFUL stand-in for its
 * gateway routes, in the real response shapes:
 *
 *  - agents: app/gateway/routers/agents.py (avatar, tools, notify; every write
 *    a version, a stale base_version is a 409, undo restores a version);
 *  - the tool catalog: app/gateway/tool_catalog.py (Gmail connected with its
 *    tools' tiers, Slack not connected, the filesystem and a custom MCP
 *    server, the built-ins);
 *  - autonomy (tasks, notes, archive, drafts), drafts (agent: integrations,
 *    skill), schedules (schedule-stubs.ts' rule file: the 006-F routes);
 *  - skills: custom skill content, files, the Studio record (icon, colour,
 *    saved tests) and the test route (3 tries, saved with the skill).
 *
 * Later routes win in Playwright, so these override the chat bar's. `seen`
 * records what reached the "server".
 */

export interface StudioSeen {
  agentWrites: {
    method: string;
    url: string;
    body: Record<string, unknown>;
  }[];
  autonomyPuts: { agent: string; granted: string[]; base_version: number }[];
  drafts: { kind: string; body: Record<string, unknown> }[];
  skillWrites: { method: string; url: string; body: unknown }[];
  skillTests: {
    name: string;
    message: string;
    tries: number;
    save: boolean;
  }[];
  undos: { url: string; body: unknown }[];
  rules: Awaited<ReturnType<typeof ruleFile>>;
}

const T = (
  name: string,
  short: string,
  label: string,
  tier: 1 | 2 | 3 | null,
  common = true,
  description = "",
) => ({ name, short, label, description, tier, common });

export const CATALOG = {
  rules_error: null,
  connectors_available: true,
  integrations: [
    {
      id: "connector:GMAIL",
      name: "Gmail",
      kind: "app",
      status: "connected",
      detail: "Productivity",
      tools: [
        T(
          "connector-gmail_GMAIL_FETCH_EMAILS",
          "GMAIL_FETCH_EMAILS",
          "Fetch emails",
          1,
          true,
          "Find email by sender, subject or words.",
        ),
        T(
          "connector-gmail_GMAIL_FETCH_MESSAGE_BY_THREAD_ID",
          "GMAIL_FETCH_MESSAGE_BY_THREAD_ID",
          "Fetch message by thread id",
          1,
          true,
          "Open one conversation.",
        ),
        T(
          "connector-gmail_GMAIL_CREATE_EMAIL_DRAFT",
          "GMAIL_CREATE_EMAIL_DRAFT",
          "Create email draft",
          2,
          true,
          "Writes a draft in Drafts; you send it.",
        ),
        T(
          "connector-gmail_GMAIL_ADD_LABEL_TO_EMAIL",
          "GMAIL_ADD_LABEL_TO_EMAIL",
          "Add label to email",
          2,
          true,
          "Tags a thread, easy to undo.",
        ),
        T(
          "connector-gmail_GMAIL_MOVE_TO_TRASH",
          "GMAIL_MOVE_TO_TRASH",
          "Move to trash",
          3,
          true,
          "Moves a message to Trash.",
        ),
        T(
          "connector-gmail_GMAIL_LIST_LABELS",
          "GMAIL_LIST_LABELS",
          "List labels",
          1,
          false,
        ),
        T(
          "connector-gmail_GMAIL_GET_PROFILE",
          "GMAIL_GET_PROFILE",
          "Get profile",
          1,
          false,
        ),
        T(
          "connector-gmail_GMAIL_SEND_EMAIL",
          "GMAIL_SEND_EMAIL",
          "Send email",
          null,
          false,
          "Sends an email.",
        ),
      ],
    },
    {
      id: "connector:GOOGLECALENDAR",
      name: "Google Calendar",
      kind: "app",
      status: "connected",
      detail: "Productivity",
      tools: [
        T(
          "connector-googlecalendar_GOOGLECALENDAR_FIND_EVENT",
          "GOOGLECALENDAR_FIND_EVENT",
          "Find event",
          1,
        ),
        T(
          "connector-googlecalendar_GOOGLECALENDAR_FIND_FREE_SLOTS",
          "GOOGLECALENDAR_FIND_FREE_SLOTS",
          "Find free slots",
          1,
        ),
        T(
          "connector-googlecalendar_GOOGLECALENDAR_CREATE_EVENT",
          "GOOGLECALENDAR_CREATE_EVENT",
          "Create event",
          3,
          true,
          "Sends invitations to others.",
        ),
      ],
    },
    {
      id: "connector:SLACK",
      name: "Slack",
      kind: "app",
      status: "not_connected",
      detail: "Communication",
      tools: [],
    },
    {
      id: "local:filesystem",
      name: "filesystem",
      kind: "mcp",
      status: "connected",
      detail: "Files in ~/workspace (sandboxed)",
      tools: [
        T("filesystem_read_file", "read_file", "Read file", 1),
        T("filesystem_edit_file", "edit_file", "Edit file", 2),
      ],
    },
    {
      id: "local:judging-board",
      name: "judging-board",
      kind: "custom",
      status: "unreachable",
      detail: "Not answering right now",
      tools: [],
    },
    {
      id: "builtin:web",
      name: "Web",
      kind: "builtin",
      status: "connected",
      detail: "Search the web and open pages",
      tools: [
        T("web_search", "web_search", "Web search", 1),
        T("web_fetch", "web_fetch", "Web fetch", 1),
      ],
    },
    {
      id: "builtin:ledger",
      name: "Tasks and notes",
      kind: "builtin",
      status: "connected",
      detail: "Your projects, tasks and decisions",
      tools: [
        T("ledger_read", "ledger_read", "Ledger read", 1),
        T("ledger_apply", "ledger_apply", "Ledger apply", 2),
      ],
    },
  ],
};

export const WRAP_UP = {
  name: "evening-wrap-up",
  display_name: "Evening wrap-up",
  description:
    "Tells you what moved and what's stuck, every weekday at 6:00 PM",
  model: null,
  tool_groups: null,
  skills: ["cite-every-claim", "project-status-format"],
  projects: [],
  avatar: "snooze",
  tools: {
    integrations: ["builtin:ledger", "builtin:web", "connector:GMAIL"],
    tools: [
      "connector-gmail_GMAIL_CREATE_EMAIL_DRAFT",
      "connector-gmail_GMAIL_FETCH_EMAILS",
      "ledger_apply",
      "ledger_read",
      "web_search",
    ],
  },
  notify: { telegram: true, home: true },
  soul: "You are my end-of-day partner. Every weekday at 6 PM, look at what changed today across my projects and write a short wrap-up. Lead with anything stuck for more than a day.",
};

const AGENTS = [
  WRAP_UP,
  {
    name: "researcher",
    display_name: "Researcher",
    description: "Digs into a question and cites every source it used",
    model: null,
    tool_groups: ["web"],
    skills: null,
    projects: [],
    avatar: "pip",
    tools: null,
    notify: null,
    soul: "You research questions and cite your sources.",
  },
  {
    name: "inbox-triage",
    display_name: "Inbox triage",
    description: "Labels routine email and drafts replies for you to send",
    model: null,
    tool_groups: null,
    skills: [],
    projects: [],
    avatar: "mochi",
    tools: {
      integrations: ["connector:GMAIL"],
      tools: ["connector-gmail_GMAIL_FETCH_EMAILS"],
    },
    notify: null,
    soul: "",
  },
];

const SKILL = (name: string, description: string, category: string) => ({
  name,
  description,
  category,
  license: "",
  enabled: true,
});

export const SKILLS = [
  SKILL(
    "cite-every-claim",
    "Any answer that states facts from the web, email or files.",
    "custom",
  ),
  SKILL(
    "project-status-format",
    "When someone asks where a project stands, for a wrap-up, or for a weekly or daily status.",
    "custom",
  ),
  SKILL(
    "deep-research",
    "Questions that need several sources compared, not one quick answer.",
    "public",
  ),
  SKILL(
    "web-app-builder",
    "When asked to build, prototype or fix a small web page or app.",
    "public",
  ),
];

export const STATUS_MD = `---
name: project-status-format
description: When someone asks where a project stands, for a wrap-up, or for a weekly or daily status.
---

## Project status

Write at most **9 lines**, in this order:

1. **Moved** — what finished or advanced today, one line each.
2. **Stuck** — anything blocked more than a day, with who it waits on.
3. **Next** — the top three tasks for tomorrow.

- Name the project in bold before each group.
- Link every task with its id, like \`T-142\`.

Use \`example-report.md\` for tone and length.
`;

const CLASSES = [
  {
    id: "tasks",
    label: "Create and update tasks",
    allows:
      "Add tasks to your projects, and change a task's title, due date or status. It never drops a task.",
  },
  {
    id: "notes",
    label: "Add notes and decisions",
    allows:
      "Write a note or a decision into a project. You can edit or remove it later.",
  },
  {
    id: "archive",
    label: "Archive stale tasks",
    allows:
      "Mark a task dropped, which hides it from the lists. Changing its status brings it back.",
  },
  {
    id: "drafts",
    label: "Draft emails (never sends)",
    allows:
      "Save email drafts in your mailbox for you to read and send. It never sends one.",
  },
];

const TEST_TRIES = (hits: number) =>
  [0, 1, 2].map((i) => ({ loaded: i < hits, other_skills: [], error: null }));

export interface StudioStubOptions {
  /** Rules already in the rule file (other agents' schedules). */
  schedules?: ScheduleRule[];
  /** Every agent PUT is refused as stale (409). */
  staleAgents?: boolean;
}

export async function stubStudio(
  page: Page,
  { schedules = [], staleAgents = false }: StudioStubOptions = {},
): Promise<StudioSeen> {
  await chatBarStub(page);
  const rules = await ruleFile(page);
  rules.rules.push(...schedules);
  const seen: StudioSeen = {
    agentWrites: [],
    autonomyPuts: [],
    drafts: [],
    skillWrites: [],
    skillTests: [],
    undos: [],
    rules,
  };
  const store = new Map<
    string,
    { versions: Record<string, unknown>[]; grants: string[] }
  >();
  for (const a of AGENTS)
    store.set(a.name, {
      versions: [{ ...a }],
      grants: a.name === "evening-wrap-up" ? ["tasks", "notes"] : [],
    });
  const current = (name: string) => {
    const rec = store.get(name)!;
    return { ...rec.versions.at(-1)!, version: rec.versions.length };
  };

  await page.route("**/api/agents", async (route) => {
    const req = route.request();
    if (req.method() === "POST") {
      const body = req.postDataJSON() as Record<string, unknown>;
      seen.agentWrites.push({ method: "POST", url: req.url(), body });
      const name = String(body.name).toLowerCase();
      if (store.has(name))
        return json(route, { detail: `Agent '${name}' already exists` }, 409);
      const record = {
        model: null,
        tool_groups: null,
        projects: null,
        display_name: null,
        notify: null,
        tools: null,
        skills: null,
        ...body,
        name,
        avatar: body.avatar ?? "pip",
      };
      delete (record as Record<string, unknown>).source;
      store.set(name, { versions: [record], grants: [] });
      return json(route, current(name), 201);
    }
    return json(route, { agents: [...store.keys()].map(current) });
  });
  await page.route("**/api/agents/*/versions", (route) => {
    const name = decodeURIComponent(route.request().url().split("/").at(-2)!);
    const versions = store.get(name)?.versions ?? [];
    return json(route, {
      name,
      current: versions.length,
      versions: versions
        .map((_, i) => ({
          version: i + 1,
          at: "2026-10-20T10:00:00Z",
          who: "user:u1",
          source: i === 0 ? "existing" : "manual",
          changed: i === 0 ? [] : ["config.display_name"],
          deleted: false,
        }))
        .reverse(),
    });
  });
  await page.route("**/api/agents/*/undo", (route) => {
    const req = route.request();
    const name = decodeURIComponent(req.url().split("/").at(-2)!);
    const body = req.postDataJSON() as {
      to_version: number;
      base_version: number;
    };
    seen.undos.push({ url: req.url(), body });
    const rec = store.get(name)!;
    rec.versions.push({ ...rec.versions[body.to_version - 1]! });
    return json(route, { name, current: rec.versions.length, versions: [] });
  });
  await page.route("**/api/agents/*", async (route) => {
    const req = route.request();
    const name = decodeURIComponent(
      new URL(req.url()).pathname.split("/").at(-1)!,
    );
    if (name === "check") return json(route, { available: true, name });
    if (!store.has(name))
      return json(route, { detail: `Agent '${name}' not found` }, 404);
    if (req.method() === "PUT") {
      const body = req.postDataJSON() as Record<string, unknown>;
      seen.agentWrites.push({ method: "PUT", url: req.url(), body });
      const rec = store.get(name)!;
      if (staleAgents || body.base_version !== rec.versions.length)
        return json(
          route,
          {
            detail: `agent '${name}' changed since you opened it (you had version ${String(body.base_version)}, it is now version ${rec.versions.length}). Reload to see the change, then try again.`,
          },
          409,
        );
      const next = { ...rec.versions.at(-1)! };
      for (const [k, v] of Object.entries(body))
        if (k !== "base_version" && k !== "source") next[k] = v;
      rec.versions.push(next);
      return json(route, current(name));
    }
    return json(route, current(name));
  });

  await page.route("**/api/studio/tool-catalog", (route) =>
    json(route, CATALOG),
  );
  await page.route("**/api/channels/", (route) =>
    json(route, {
      service_running: true,
      channels: { telegram: { enabled: true, running: true } },
    }),
  );
  await page.route("**/api/studio/agents/*/autonomy", (route) => {
    const req = route.request();
    const name = decodeURIComponent(req.url().split("/").at(-2)!);
    const rec = store.get(name);
    const view = () => ({
      agent: name,
      version: rec ? rec.versions.length : 0,
      classes: CLASSES.map((k) => ({
        ...k,
        granted: !!rec?.grants.includes(k.id),
        grantable: true,
        not_grantable_reason: "",
      })),
      cap_per_run: 20,
      always_waits: ["task"],
      rules_error: null,
    });
    if (req.method() === "PUT") {
      const body = req.postDataJSON() as {
        granted: string[];
        base_version: number;
      };
      seen.autonomyPuts.push({ agent: name, ...body });
      if (rec) {
        rec.grants = [...body.granted];
        rec.versions.push({ ...rec.versions.at(-1)! });
      }
    }
    return json(route, view());
  });
  await page.route("**/api/studio/agents/*/grant-uses", (route) =>
    json(route, []),
  );
  await page.route("**/api/drafts/*", (route) => {
    const req = route.request();
    const kind = req.url().split("/").at(-1)!;
    const body = req.postDataJSON() as Record<string, unknown>;
    seen.drafts.push({ kind, body });
    if (kind === "agent")
      return json(route, {
        kind,
        model: "test-model",
        agent: {
          display_name: "Morning planner",
          description: "Plans your morning",
          instructions:
            "You are my morning planner. Every weekday at 8:00 AM, read what arrived in my inbox overnight and what is on my calendar today, then send me a plan in five lines or fewer.",
          tool_groups: [],
          skills: ["project-status-format"],
          projects: [],
          autonomy: ["tasks", "drafts"],
          schedule: { cron: "0 8 * * 1-5", timezone: "America/New_York" },
          integrations: ["connector:GMAIL", "builtin:ledger"],
        },
        skill: null,
        dropped: [],
      });
    return json(route, {
      kind,
      model: "test-model",
      agent: null,
      skill: {
        name: "Release notes",
        description: "When summarising merged pull requests for a release.",
        body: "## Release notes\n\n1. **Group** — by area.\n2. **Link** — each pull request.\n\n- Keep it short.",
      },
      dropped: [],
    });
  });

  // -- skills ----------------------------------------------------------------
  const skills = SKILLS.map((s) => ({ ...s }));
  const content = new Map<string, { content: string; version: number }>([
    ["project-status-format", { content: STATUS_MD, version: 4 }],
    [
      "cite-every-claim",
      {
        content:
          "---\nname: cite-every-claim\ndescription: Any answer that states facts from the web, email or files.\n---\n\n# Cite\n\nCite every claim.\n",
        version: 1,
      },
    ],
  ]);
  const files = new Map<string, { path: string; size: number }[]>([
    [
      "project-status-format",
      [
        { path: "references/example-report.md", size: 2048 },
        { path: "scripts/score_risk.py", size: 4096 },
      ],
    ],
  ]);
  const studio = new Map<
    string,
    { icon: string | null; color: number | null; tests: unknown[] }
  >([
    [
      "project-status-format",
      {
        icon: "list",
        color: 6,
        tests: [
          {
            message: "Where are we on HackMIT judging?",
            at: "2026-10-20T10:00:00Z",
            model: "test-model",
            listed: true,
            loaded: 3,
            total: 3,
            tries: TEST_TRIES(3),
          },
          {
            message: "Anything slipping this week?",
            at: "2026-10-20T10:00:00Z",
            model: "test-model",
            listed: true,
            loaded: 1,
            total: 3,
            tries: TEST_TRIES(1),
          },
        ],
      },
    ],
  ]);
  const describe = (md: string) =>
    /^description:\s*"?(.*?)"?\s*$/m.exec(md)?.[1] ?? "";
  const segment = (url: string, back: number) =>
    decodeURIComponent(new URL(url).pathname.split("/").at(-back)!);

  await page.route("**/api/skills", (route) => json(route, { skills }));
  await page.route("**/api/skills/custom", async (route) => {
    const req = route.request();
    if (req.method() === "POST") {
      const body = req.postDataJSON() as { name: string; content: string };
      seen.skillWrites.push({ method: "POST", url: req.url(), body });
      skills.push(SKILL(body.name, describe(body.content), "custom"));
      content.set(body.name, { content: body.content, version: 1 });
      return json(
        route,
        {
          ...SKILL(body.name, describe(body.content), "custom"),
          content: body.content,
          version: 1,
        },
        201,
      );
    }
    return json(route, {
      skills: skills.filter((s) => s.category === "custom"),
    });
  });
  await page.route("**/api/skills/custom/*", async (route) => {
    const req = route.request();
    const name = segment(req.url(), 1);
    const rec = content.get(name);
    if (req.method() === "PUT") {
      const body = req.postDataJSON() as {
        content: string;
        base_version: number;
      };
      seen.skillWrites.push({ method: "PUT", url: req.url(), body });
      const next = { content: body.content, version: (rec?.version ?? 0) + 1 };
      content.set(name, next);
      const s = skills.find((x) => x.name === name)!;
      s.description = describe(body.content) || s.description;
      return json(route, {
        ...s,
        content: next.content,
        version: next.version,
      });
    }
    if (!rec) return json(route, { detail: "not found" }, 404);
    return json(route, {
      ...skills.find((s) => s.name === name)!,
      content: rec.content,
      version: rec.version,
    });
  });
  await page.route("**/api/skills/custom/*/files**", async (route) => {
    const req = route.request();
    const name = segment(req.url(), 2);
    const list = files.get(name) ?? [];
    if (req.method() === "POST") {
      const body = req.postDataJSON() as { path: string; content: string };
      seen.skillWrites.push({ method: "POST", url: req.url(), body });
      files.set(name, [
        ...list.filter((f) => f.path !== body.path),
        { path: body.path, size: body.content.length },
      ]);
    } else if (req.method() === "DELETE") {
      const path = new URL(req.url()).searchParams.get("path");
      seen.skillWrites.push({
        method: "DELETE",
        url: req.url(),
        body: { path },
      });
      files.set(
        name,
        list.filter((f) => f.path !== path),
      );
    }
    return json(route, { skill_name: name, files: files.get(name) ?? [] });
  });
  await page.route("**/api/skills/custom/*/studio", async (route) => {
    const req = route.request();
    const name = segment(req.url(), 2);
    const rec = studio.get(name) ?? { icon: null, color: null, tests: [] };
    if (req.method() === "PUT") {
      const body = req.postDataJSON() as { icon: string; color: number };
      seen.skillWrites.push({ method: "PUT", url: req.url(), body });
      studio.set(name, { ...rec, ...body });
    }
    return json(route, studio.get(name) ?? rec);
  });
  await page.route("**/api/skills/custom/*/tests**", async (route) => {
    const req = route.request();
    const name = segment(req.url(), 2);
    const message = new URL(req.url()).searchParams.get("message");
    const rec = studio.get(name) ?? { icon: null, color: null, tests: [] };
    rec.tests = rec.tests.filter(
      (t) => (t as { message: string }).message !== message,
    );
    studio.set(name, rec);
    return json(route, rec);
  });
  await page.route("**/api/skills/*/test", async (route) => {
    const req = route.request();
    const name = segment(req.url(), 2);
    const body = req.postDataJSON() as {
      message: string;
      tries: number;
      save: boolean;
    };
    seen.skillTests.push({ name, ...body });
    const hits = /status|where|wrap|stuck|going/i.test(body.message)
      ? 3
      : /week|slip/i.test(body.message)
        ? 1
        : 0;
    const tries = TEST_TRIES(hits);
    if (body.save) {
      const rec = studio.get(name) ?? { icon: null, color: null, tests: [] };
      rec.tests = [
        {
          message: body.message,
          at: new Date().toISOString(),
          model: "test-model",
          listed: true,
          loaded: hits,
          total: 3,
          tries,
        },
        ...rec.tests.filter(
          (t) => (t as { message: string }).message !== body.message,
        ),
      ];
      studio.set(name, rec);
    }
    return json(route, {
      skill: name,
      model: "test-model",
      listed: true,
      tries,
      loaded: hits,
      total: 3,
    });
  });
  return seen;
}
