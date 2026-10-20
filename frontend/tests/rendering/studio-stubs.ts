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
}

export async function stubStudio(
  page: Page,
  { agentsDisabled = false }: StudioStubOptions = {},
): Promise<StudioSeen> {
  await chatBarStub(page);
  const seen: StudioSeen = {
    agentWrites: [],
    skillWrites: [],
    drafts: [],
    autonomyPuts: [],
    tests: [],
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
  await page.route("**/api/agents/*", async (route) => {
    const method = route.request().method();
    const name = decodeURIComponent(route.request().url().split("/").pop()!);
    const agent = agents.find((a) => a.name === name);
    if (method === "PUT") {
      const body = route.request().postDataJSON() as Record<string, unknown>;
      seen.agentWrites.push({ method, url: route.request().url(), body });
      Object.assign(agent ?? {}, body);
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
        schedules: [],
        recent: [],
      });
    }
    return json(route, {
      agent: name,
      engine_enabled: true,
      not_set_up_reason: null,
      rules_error: null,
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
    return json(route, { ...SKILLS.find((s) => s.name === name), content });
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
