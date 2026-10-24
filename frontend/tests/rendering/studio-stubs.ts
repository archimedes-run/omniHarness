import type { Page } from "@playwright/test";

import { json, stub as chatBarStub } from "./chat-bar-stubs";

/**
 * Agent Studio and Skill Studio stubs (Feature 006, Phase 3): the shell's
 * usual stubs, then the agents, skills and studio routes with data shaped
 * like the gateway's. Later routes win in Playwright, so these override the
 * chat bar's agents and skills. `seen` records what the panels wrote.
 */
export interface StudioSeen {
  agentWrites: { method: string; url: string; body: unknown }[];
  skillWrites: { method: string; url: string; body: unknown }[];
  drafts: unknown[];
  autonomyPuts: unknown[];
  tests: unknown[];
  undos: { url: string; body: unknown }[];
}

export const WRAP_UP = {
  name: "evening-wrap-up",
  display_name: "Evening wrap-up",
  description:
    "Tells you what moved and what's stuck, every weekday at 6:00 PM",
  model: null,
  tool_groups: ["web", "file:read"],
  skills: ["cite-every-claim", "project-status-format"],
  projects: ["p1"],
  version: 3,
  soul: "You are my evening wrap-up. For each project I'm working on:\n1. What moved today.\n2. What is stuck.\n3. The one thing to start with tomorrow, and why.",
};

const AGENTS = [
  {
    name: "researcher",
    description: "Finds sources and cites them",
    model: null,
    tool_groups: null,
    skills: null,
    soul: "",
  },
  WRAP_UP,
  {
    name: "release-manager",
    display_name: "Release manager",
    description: "Ships slices",
    model: null,
    tool_groups: ["bash"],
    skills: ["project-status-format"],
    projects: [],
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
  SKILL("cite-every-claim", "Use when stating facts.", "custom"),
  SKILL(
    "project-status-format",
    'Use when reporting the status of a project, a task, or a coding session: briefings, wrap-ups, and "where are we on X" questions.',
    "custom",
  ),
  SKILL("deep-research", "Use for multi-source research.", "public"),
  SKILL("web-app-builder", "Use to build a small web app.", "public"),
];

export const STATUS_MD = `---
name: project-status-format
description: "Use when reporting the status of a project, a task, or a coding session: briefings, wrap-ups, and \\"where are we on X\\" questions."
---

# Status report format

Open with one line: on track, at risk, or blocked, and why.
- Moved: what finished, with its evidence.
- Stuck: what is waiting and on whom.
- Next: the one most useful step.
Mark each item "observed" or "reported".
`;

export interface StudioStubOptions {
  agentsDisabled?: boolean;
  /** Every agent PUT is refused as stale (409). */
  staleAgents?: boolean;
}

export async function stubStudio(
  page: Page,
  { agentsDisabled = false, staleAgents = false }: StudioStubOptions = {},
): Promise<StudioSeen> {
  await chatBarStub(page);
  const seen: StudioSeen = {
    agentWrites: [],
    skillWrites: [],
    drafts: [],
    autonomyPuts: [],
    tests: [],
    undos: [],
  };
  const agents = AGENTS.map((a) => ({ ...a }));

  await page.route("**/api/agents", async (route) => {
    const method = route.request().method();
    if (agentsDisabled) {
      return json(
        route,
        {
          detail:
            "Custom-agent management API is disabled. Set agents_api.enabled=true",
        },
        403,
      );
    }
    if (method === "POST") {
      const body = route.request().postDataJSON() as { name: string };
      seen.agentWrites.push({ method, url: route.request().url(), body });
      agents.push({ ...(body as (typeof agents)[number]) });
      return json(route, body, 201);
    }
    return json(route, { agents });
  });
  const VERSIONS = {
    current: 3,
    versions: [
      {
        version: 3,
        at: new Date().toISOString(),
        who: "user:u1",
        source: "draft",
        changed: ["soul"],
        deleted: false,
      },
      {
        version: 2,
        at: new Date(Date.now() - 86_400_000).toISOString(),
        who: "agent:evening-wrap-up",
        source: "proposal",
        changed: ["config.description"],
        deleted: false,
      },
      {
        version: 1,
        at: new Date(Date.now() - 2 * 86_400_000).toISOString(),
        who: "user:u1",
        source: "manual",
        changed: ["created"],
        deleted: false,
      },
    ],
  };
  await page.route("**/api/agents/*/versions", (route) =>
    json(route, { name: "evening-wrap-up", ...VERSIONS }),
  );
  await page.route("**/api/skills/custom/*/versions", (route) =>
    json(route, { name: "project-status-format", ...VERSIONS }),
  );
  for (const glob of ["**/api/agents/*/undo", "**/api/skills/custom/*/undo"]) {
    await page.route(glob, (route) => {
      seen.undos.push({
        url: route.request().url(),
        body: route.request().postDataJSON(),
      });
      return json(route, { name: "x", ...VERSIONS });
    });
  }
  await page.route("**/api/agents/*", async (route) => {
    const method = route.request().method();
    const name = decodeURIComponent(route.request().url().split("/").pop()!);
    const agent = agents.find((a) => a.name === name);
    if (method === "PUT") {
      const body = route.request().postDataJSON() as Record<string, unknown>;
      seen.agentWrites.push({ method, url: route.request().url(), body });
      if (staleAgents) {
        return json(
          route,
          {
            detail:
              "agent 'evening-wrap-up' changed since you opened it (you had version 3, it is now version 4). Reload to see the change, then try again.",
          },
          409,
        );
      }
      Object.assign(agent ?? {}, body);
      if (agent)
        (agent as { version?: number }).version =
          ((agent as { version?: number }).version ?? 0) + 1;
      return json(route, agent);
    }
    return agent ? json(route, agent) : json(route, { detail: "nope" }, 404);
  });
  await page.route("**/api/studio/agents/*/runs", (route) => {
    const name = decodeURIComponent(route.request().url().split("/").at(-2)!);
    const next = new Date(Date.now() + 26 * 3_600_000).toISOString();
    if (name !== "evening-wrap-up" && name !== "lead_agent") {
      return json(route, {
        agent: name,
        engine_enabled: true,
        not_set_up_reason: "none-name-this-agent",
        rules_error: null,
        rules_version: "v1",
        writable: true,
        schedules: [],
        recent: [],
      });
    }
    return json(route, {
      agent: name,
      engine_enabled: true,
      not_set_up_reason: null,
      rules_error: null,
      rules_version: "v1",
      writable: true,
      schedules: [
        {
          rule_id: "evening-wrap",
          schedule: "0 18 * * 1-5",
          timezone: "America/New_York",
          timezone_named: true,
          enabled: true,
          next_run: next,
          held_until: null,
          error: null,
          name: "Evening wrap-up",
          prompt: "Wrap up my day as of {scheduled_at}.",
          telegram: true,
          show_on_home: true,
        },
      ],
      recent: [
        {
          at: new Date(Date.now() - 3_600_000).toISOString(),
          rule_id: "evening-wrap",
          event_type: "cron",
          event_id: "e2",
          outcome: "delivered",
          reason: "",
          batch: "alone",
          batch_id: null,
          delivered_with: [],
        },
        {
          at: new Date(Date.now() - 3 * 86_400_000).toISOString(),
          rule_id: "evening-wrap",
          event_type: "cron",
          event_id: "e1",
          outcome: "queued",
          reason: "quiet hours 22:00-07:30",
          batch: "alone",
          batch_id: null,
          delivered_with: [],
        },
      ],
    });
  });
  await page.route("**/api/drafts/*", (route) => {
    const kind = route.request().url().split("/").pop();
    seen.drafts.push({ kind, ...route.request().postDataJSON() });
    return kind === "agent"
      ? json(route, {
          kind,
          model: "default",
          agent: {
            display_name: "Morning brief",
            description: "Tells you what is waiting each morning",
            instructions: "You are my morning brief.\n1. What is waiting.",
            tool_groups: ["web"],
            skills: ["cite-every-claim"],
            projects: ["p1"],
            autonomy: ["tasks"],
            schedule: { cron: "30 7 * * 1-5", timezone: "America/New_York" },
          },
          skill: null,
          dropped: ["teleport"],
        })
      : json(route, {
          kind,
          model: "default",
          agent: null,
          skill: {
            name: "Status report",
            description: "Use when someone asks where things stand.",
            body: "# Status\n\n- Moved",
          },
          dropped: [],
        });
  });
  const autonomy = {
    version: 3,
    granted: ["tasks", "notes"] as string[],
  };
  await page.route("**/api/studio/agents/*/autonomy", (route) => {
    const agent = decodeURIComponent(route.request().url().split("/").at(-2)!);
    if (route.request().method() === "PUT") {
      const body = route.request().postDataJSON() as { granted: string[] };
      seen.autonomyPuts.push({ agent, ...body });
      autonomy.granted = body.granted;
      autonomy.version += 1;
    }
    const mine = agent === "evening-wrap-up" ? autonomy.granted : [];
    return json(route, {
      agent,
      version: agent === "evening-wrap-up" ? autonomy.version : 0,
      cap_per_run: 20,
      rules_error: null,
      always_waits: [
        "task",
        "mcp_build",
        "filesystem_delete*",
        "googlecalendar_delete_event",
        "googlecalendar_update_event",
        "connector-gmail_GMAIL_DELETE_MESSAGE",
        "github_add_issue_comment",
        "github_create_issue",
        "github_merge_pull_request",
        "github_create_repository",
      ],
      classes: [
        {
          id: "tasks",
          label: "Create and update tasks",
          allows:
            "Add tasks to your projects, and change a task's title, due date or status. It never drops a task.",
          granted: mine.includes("tasks"),
          grantable: true,
          not_grantable_reason: "",
        },
        {
          id: "notes",
          label: "Add notes and decisions",
          allows:
            "Write a note or a decision into a project. You can edit or remove it later.",
          granted: mine.includes("notes"),
          grantable: true,
          not_grantable_reason: "",
        },
        {
          id: "archive",
          label: "Archive stale tasks",
          allows:
            "Mark a task dropped, which hides it from the lists. Changing its status brings it back.",
          granted: mine.includes("archive"),
          grantable: true,
          not_grantable_reason: "",
        },
      ],
    });
  });
  await page.route("**/api/studio/agents/*/grant-uses", (route) => {
    const agent = decodeURIComponent(route.request().url().split("/").at(-2)!);
    return json(
      route,
      agent === "evening-wrap-up"
        ? [
            {
              at: new Date(Date.now() - 3_600_000).toISOString(),
              tool: "ledger_apply",
              classes: ["tasks"],
              targets: ["Add task “Follow up on judging” to “HackMIT 2026”"],
              thread_id: "t-run",
              rule_id: "evening-wrap",
              origin: "content",
              origin_source: "web_fetch",
              count_in_run: 1,
            },
          ]
        : [],
    );
  });
  await page.route("**/api/skills/*/test", (route) => {
    const body = route.request().postDataJSON() as { message: string };
    seen.tests.push(body);
    const tweet = /tweet/i.test(body.message);
    return json(route, {
      skill: "project-status-format",
      model: "default",
      listed: true,
      tries: tweet
        ? [
            { loaded: false, other_skills: [], error: null },
            { loaded: false, other_skills: [], error: null },
            { loaded: false, other_skills: [], error: "TimeoutError: slow" },
          ]
        : [
            { loaded: true, other_skills: [], error: null },
            { loaded: true, other_skills: ["cite-every-claim"], error: null },
            { loaded: false, other_skills: [], error: null },
          ],
      loaded: tweet ? 0 : 2,
      total: 3,
    });
  });
  await page.route("**/api/studio/options", (route) =>
    json(route, {
      tool_groups: ["web", "file:read", "file:write", "bash"],
      default_model: "default",
    }),
  );
  await page.route("**/api/ledger/projects", (route) =>
    json(route, [
      {
        id: "p1",
        name: "OmniHarness",
        why: null,
        status: "active",
        context: null,
        version: 1,
        created_at: "2026-10-01T00:00:00+00:00",
        updated_at: "2026-10-01T00:00:00+00:00",
        open_tasks: 3,
        overdue: 0,
        done_tasks: 1,
      },
      {
        id: "p2",
        name: "HackMIT 2026",
        why: null,
        status: "active",
        context: null,
        version: 1,
        created_at: "2026-10-01T00:00:00+00:00",
        updated_at: "2026-10-01T00:00:00+00:00",
        open_tasks: 0,
        overdue: 0,
        done_tasks: 0,
      },
    ]),
  );
  await page.route("**/api/skills", (route) => json(route, { skills: SKILLS }));
  await page.route("**/api/skills/custom", async (route) => {
    const body = route.request().postDataJSON() as { name: string };
    seen.skillWrites.push({
      method: route.request().method(),
      url: route.request().url(),
      body,
    });
    return json(route, { ...SKILL(body.name, "", "custom"), content: "" }, 201);
  });
  await page.route("**/api/skills/custom/*", async (route) => {
    const name = decodeURIComponent(route.request().url().split("/").pop()!);
    if (route.request().method() === "PUT") {
      seen.skillWrites.push({
        method: "PUT",
        url: route.request().url(),
        body: route.request().postDataJSON(),
      });
    }
    const content =
      name === "project-status-format"
        ? STATUS_MD
        : `---\nname: ${name}\ndescription: Use when stating facts.\n---\n\nCite every claim.\n`;
    return json(route, {
      ...SKILLS.find((s) => s.name === name),
      content,
      version: 3,
    });
  });
  await page.route("**/api/skills/custom/*/files", (route) =>
    json(route, {
      skill_name: "project-status-format",
      files: [
        { path: "references/example-report.md", size: 2048 },
        { path: "scripts/score_risk.py", size: 4096 },
      ],
    }),
  );
  return seen;
}
