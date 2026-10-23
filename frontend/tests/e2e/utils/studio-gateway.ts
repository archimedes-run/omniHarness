import type { Page, Route } from "@playwright/test";

/**
 * A STATEFUL stand-in for the gateway's Studio routes, for the Agent Studio
 * and Skill Studio end-to-end tests (Feature 006, Phase 3).
 *
 * The e2e suite runs with no backend (playwright.config.ts starts only the
 * frontend), so these routes answer with the RESPONSE SHAPES of the real
 * routers and keep state the way the real store does:
 *
 *  - agents: app/gateway/routers/agents.py (AgentResponse, AgentsListResponse,
 *    AgentVersionsResponse). Every write is a version in one store
 *    (omniharness/config/config_versions.py): create is v1, a PUT names the
 *    base_version it was made from and is refused (409, the store's own
 *    message) when that is stale, and undo restores an earlier version's
 *    content AS A NEW VERSION (grants are never restored by undo);
 *  - drafts: app/gateway/routers/drafts.py (DraftResponse); a fake model
 *    answers, and only names that exist come back (the rest are `dropped`);
 *  - autonomy: app/gateway/routers/studio.py (AutonomyView); a grant change
 *    is the agent's next version;
 *  - custom skills: app/gateway/routers/skills.py (CustomSkill, versions,
 *    undo, files) and the Test route (SkillTestResponse, `tries` per try).
 *
 * `state` is exposed so a test can assert what reached the "server".
 */

export interface AgentRecord {
  name: string;
  display_name: string | null;
  description: string;
  model: string | null;
  tool_groups: string[] | null;
  skills: string[] | null;
  projects: string[] | null;
  soul: string;
  autonomy: string[];
}

interface Version<T> {
  version: number;
  at: string;
  who: string;
  source: string;
  changed: string[];
  deleted: boolean;
  snapshot: T;
}

export interface SkillRecord {
  name: string;
  content: string;
  enabled: boolean;
}

export interface GatewayState {
  agents: Map<string, { versions: Version<AgentRecord>[] }>;
  skills: Map<string, { versions: Version<SkillRecord>[] }>;
  drafts: { kind: string; body: Record<string, unknown> }[];
  agentWrites: {
    method: string;
    name: string;
    body: Record<string, unknown>;
  }[];
  autonomyPuts: { agent: string; granted: string[]; base_version: number }[];
  undos: {
    kind: string;
    name: string;
    to_version: number;
    base_version: number;
  }[];
  skillTests: { name: string; message: string; tries: number }[];
  /** Put an agent in the store as version 1, as if created earlier. */
  seedAgent: (record: Partial<AgentRecord> & { name: string }) => void;
}

const USER = "user:u1";
const PROJECTS = [
  { id: "p-omni", name: "OmniHarness" },
  { id: "p-hack", name: "HackMIT 2026" },
];
const TOOL_GROUPS = ["web", "file:read", "file:write", "bash"];
const PUBLIC_SKILLS = [
  {
    name: "deep-research",
    description: "Use for multi-source research.",
    category: "public",
    license: "",
    enabled: true,
  },
];
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
];

const json = (route: Route, body: unknown, status = 200) =>
  route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });

function changedFields(before: AgentRecord | null, after: AgentRecord) {
  if (!before) return ["created"];
  const out: string[] = [];
  for (const key of Object.keys(after) as (keyof AgentRecord)[]) {
    if (key === "autonomy") continue;
    if (JSON.stringify(before[key]) !== JSON.stringify(after[key]))
      out.push(key === "soul" ? "soul" : `config.${key}`);
  }
  if (JSON.stringify(before.autonomy) !== JSON.stringify(after.autonomy))
    out.push("config.autonomy");
  return out;
}

function stale(kind: string, name: string, base: number, current: number) {
  // config_versions.StaleWriteError's own message.
  return `${kind} '${name}' changed since you opened it (you had version ${base}, it is now version ${current}). Reload to see the change, then try again.`;
}

/** The SKILL.md a create or save carries: frontmatter, then the body. */
function skillDescription(content: string) {
  const m = /^description:\s*"?(.*?)"?\s*$/m.exec(content);
  return m ? m[1]!.replace(/\\"/g, '"') : "";
}

/** The fake drafting model: deterministic from the sentence. */
function agentDraftFor(sentence: string) {
  const s = sentence.toLowerCase();
  return {
    display_name: s.includes("morning") ? "Morning brief" : "Evening wrap-up",
    description: s.includes("morning")
      ? "Tells you what is waiting each morning"
      : "Tells you what moved and what's stuck",
    instructions: s.includes("morning")
      ? "You are my morning brief.\n1. What is waiting on me.\n2. What is due today."
      : "You are my evening wrap-up.\n1. What moved today.\n2. What is stuck.",
    // The model may name things that don't exist; the server drops them.
    tool_groups: ["web", "teleport"],
    skills: ["cite-every-claim"],
    projects: ["OmniHarness", "A project nobody has"],
    autonomy: ["tasks", "send_email"],
    schedule: s.includes("weekday")
      ? { cron: "0 18 * * 1-5", timezone: "America/New_York" }
      : { cron: "30 7 * * *", timezone: null },
  };
}

export async function studioGateway(page: Page): Promise<GatewayState> {
  const state: GatewayState = {
    agents: new Map(),
    skills: new Map(),
    drafts: [],
    agentWrites: [],
    autonomyPuts: [],
    undos: [],
    skillTests: [],
    seedAgent: (record) =>
      writeAgent(
        record.name,
        {
          display_name: null,
          description: "",
          model: null,
          tool_groups: null,
          skills: null,
          projects: [],
          soul: "",
          autonomy: [],
          ...record,
        },
        "manual",
      ),
  };
  const now = () => new Date().toISOString();

  const current = (name: string) => {
    const entry = state.agents.get(name);
    return entry ? entry.versions[entry.versions.length - 1]! : null;
  };
  const agentView = (name: string) => {
    const v = current(name)!;
    // The agent's grants are not in AgentResponse (Autonomy reads them).
    const rest: Partial<AgentRecord> = { ...v.snapshot };
    delete rest.autonomy;
    return { ...rest, version: v.version };
  };
  const writeAgent = (
    name: string,
    next: AgentRecord,
    source: string,
  ): Version<AgentRecord> => {
    const entry = state.agents.get(name) ?? { versions: [] };
    const before = entry.versions.at(-1)?.snapshot ?? null;
    const version: Version<AgentRecord> = {
      version: (entry.versions.at(-1)?.version ?? 0) + 1,
      at: now(),
      who: USER,
      source,
      changed: changedFields(before, next),
      deleted: false,
      snapshot: structuredClone(next),
    };
    entry.versions.push(version);
    state.agents.set(name, entry);
    return version;
  };
  const versionsView = <T>(name: string, versions: Version<T>[]) => ({
    name,
    current: versions.at(-1)?.version ?? 0,
    versions: [...versions].reverse().map(({ snapshot: _s, ...v }) => v),
  });

  // ---- agents ----------------------------------------------------------
  await page.route("**/api/agents", async (route) => {
    const request = route.request();
    if (request.method() === "POST") {
      const body = request.postDataJSON() as Record<string, unknown>;
      const name = String(body.name).toLowerCase();
      state.agentWrites.push({ method: "POST", name, body });
      if (state.agents.has(name))
        return json(route, { detail: `Agent '${name}' already exists` }, 409);
      writeAgent(
        name,
        {
          name,
          display_name: (body.display_name as string | null) ?? null,
          description: (body.description as string) ?? "",
          model: null,
          tool_groups: (body.tool_groups as string[] | null) ?? null,
          skills: (body.skills as string[] | null) ?? null,
          projects: (body.projects as string[] | null) ?? null,
          soul: (body.soul as string) ?? "",
          autonomy: [],
        },
        (body.source as string) ?? "manual",
      );
      return json(route, agentView(name), 201);
    }
    return json(route, {
      agents: [...state.agents.keys()].map((n) => agentView(n)),
    });
  });
  await page.route("**/api/agents/*/versions", (route) => {
    const name = route.request().url().split("/").at(-2)!;
    const entry = state.agents.get(name);
    if (!entry)
      return json(route, { detail: `Agent '${name}' not found` }, 404);
    return json(route, versionsView(name, entry.versions));
  });
  await page.route("**/api/agents/*/undo", (route) => {
    const name = route.request().url().split("/").at(-2)!;
    const body = route.request().postDataJSON() as {
      to_version: number;
      base_version: number;
    };
    state.undos.push({ kind: "agent", name, ...body });
    const entry = state.agents.get(name)!;
    const head = entry.versions.at(-1)!;
    if (body.base_version !== head.version)
      return json(
        route,
        { detail: stale("agent", name, body.base_version, head.version) },
        409,
      );
    const target = entry.versions.find((v) => v.version === body.to_version);
    if (!target) return json(route, { detail: "no such version" }, 404);
    // Content comes back; the grants in force stay as they are.
    writeAgent(
      name,
      { ...structuredClone(target.snapshot), autonomy: head.snapshot.autonomy },
      "undo",
    );
    return json(route, versionsView(name, entry.versions));
  });
  await page.route("**/api/agents/*", async (route) => {
    const request = route.request();
    const name = decodeURIComponent(request.url().split("/").pop()!);
    const head = current(name);
    if (!head) return json(route, { detail: `Agent '${name}' not found` }, 404);
    if (request.method() === "PUT") {
      const body = request.postDataJSON() as Record<string, unknown>;
      state.agentWrites.push({ method: "PUT", name, body });
      if (
        typeof body.base_version === "number" &&
        body.base_version !== head.version
      )
        return json(
          route,
          { detail: stale("agent", name, body.base_version, head.version) },
          409,
        );
      const next = structuredClone(head.snapshot);
      for (const key of [
        "display_name",
        "description",
        "tool_groups",
        "skills",
        "projects",
        "soul",
      ] as const) {
        if (body[key] !== undefined && body[key] !== null)
          (next as unknown as Record<string, unknown>)[key] = body[key];
      }
      writeAgent(name, next, (body.source as string) ?? "manual");
      return json(route, agentView(name));
    }
    return json(route, agentView(name));
  });

  // ---- studio reads: options, runs, autonomy, grant uses ----------------
  await page.route("**/api/studio/options", (route) =>
    json(route, { tool_groups: TOOL_GROUPS, default_model: "default" }),
  );
  await page.route("**/api/studio/agents/*/runs", (route) => {
    const agent = route.request().url().split("/").at(-2)!;
    return json(route, {
      agent,
      engine_enabled: true,
      not_set_up_reason: "none-name-this-agent",
      rules_error: null,
      schedules: [],
      recent: [],
    });
  });
  await page.route("**/api/studio/agents/*/grant-uses", (route) =>
    json(route, []),
  );
  await page.route("**/api/studio/agents/*/autonomy", (route) => {
    const agent = decodeURIComponent(route.request().url().split("/").at(-2)!);
    if (agent !== "lead_agent" && !state.agents.has(agent))
      return json(route, { detail: `Agent '${agent}' not found` }, 404);
    if (route.request().method() === "PUT") {
      const body = route.request().postDataJSON() as {
        granted: string[];
        base_version: number;
      };
      state.autonomyPuts.push({ agent, ...body });
      const head = current(agent)!;
      if (body.base_version !== head.version)
        return json(
          route,
          { detail: stale("agent", agent, body.base_version, head.version) },
          409,
        );
      writeAgent(
        agent,
        {
          ...structuredClone(head.snapshot),
          autonomy: [...body.granted].sort(),
        },
        "manual",
      );
    }
    const head = agent === "lead_agent" ? null : current(agent);
    const granted = head?.snapshot.autonomy ?? [];
    return json(route, {
      agent,
      version: head?.version ?? 0,
      cap_per_run: 20,
      rules_error: null,
      always_waits: ["task", "mcp_build", "github_create_issue"],
      classes: CLASSES.map((c) => ({
        ...c,
        granted: granted.includes(c.id),
        grantable: true,
        not_grantable_reason: "",
      })),
    });
  });

  // ---- drafts (never saves) ---------------------------------------------
  await page.route("**/api/drafts/*", (route) => {
    const kind = route.request().url().split("/").pop()!;
    const body = route.request().postDataJSON() as Record<string, unknown>;
    state.drafts.push({ kind, body });
    if (kind === "agent") {
      const raw = agentDraftFor(String(body.sentence));
      const skillNames = [...state.skills.keys()];
      const byName = new Map(PROJECTS.map((p) => [p.name.toLowerCase(), p.id]));
      const dropped = [
        ...raw.tool_groups.filter((g) => !TOOL_GROUPS.includes(g)),
        ...raw.skills.filter((s) => !skillNames.includes(s)),
        ...raw.projects.filter((p) => !byName.has(p.toLowerCase())),
        ...raw.autonomy.filter((a) => !CLASSES.some((c) => c.id === a)),
      ];
      return json(route, {
        kind,
        model: "default",
        agent: {
          display_name: raw.display_name,
          description: raw.description,
          instructions: raw.instructions,
          tool_groups: raw.tool_groups.filter((g) => TOOL_GROUPS.includes(g)),
          skills: raw.skills.filter((s) => skillNames.includes(s)),
          projects: raw.projects
            .map((p) => byName.get(p.toLowerCase()))
            .filter(Boolean),
          autonomy: raw.autonomy.filter((a) => CLASSES.some((c) => c.id === a)),
          schedule: raw.schedule,
        },
        skill: null,
        dropped,
      });
    }
    return json(route, {
      kind,
      model: "default",
      agent: null,
      skill: {
        name: "Status report",
        description:
          "Use when someone asks where a project stands: status, wrap-ups and 'where are we on X'.",
        body: "# Status report\n\n- Open with on track, at risk or blocked.\n- Moved, stuck, next.",
      },
      dropped: [],
    });
  });

  // ---- skills -------------------------------------------------------------
  const skillList = () => [
    ...[...state.skills.entries()].map(([name, entry]) => {
      const head = entry.versions.at(-1)!.snapshot;
      return {
        name,
        description: skillDescription(head.content),
        category: "custom",
        license: "",
        enabled: head.enabled,
      };
    }),
    ...PUBLIC_SKILLS,
  ];
  const writeSkill = (name: string, content: string, source: string) => {
    const entry = state.skills.get(name) ?? { versions: [] };
    entry.versions.push({
      version: (entry.versions.at(-1)?.version ?? 0) + 1,
      at: now(),
      who: USER,
      source,
      changed: entry.versions.length ? ["SKILL.md"] : ["created"],
      deleted: false,
      snapshot: { name, content, enabled: true },
    });
    state.skills.set(name, entry);
  };
  const customView = (name: string) => {
    const head = state.skills.get(name)!.versions.at(-1)!;
    return {
      name,
      description: skillDescription(head.snapshot.content),
      category: "custom",
      enabled: head.snapshot.enabled,
      content: head.snapshot.content,
      version: head.version,
    };
  };
  await page.route("**/api/skills", (route) =>
    json(route, { skills: skillList() }),
  );
  await page.route("**/api/skills/custom", (route) => {
    const body = route.request().postDataJSON() as {
      name: string;
      content: string;
      source?: string;
    };
    if (state.skills.has(body.name))
      return json(route, { detail: "exists" }, 409);
    writeSkill(body.name, body.content, body.source ?? "manual");
    return json(route, customView(body.name), 201);
  });
  await page.route("**/api/skills/custom/*/versions", (route) => {
    const name = route.request().url().split("/").at(-2)!;
    return json(route, versionsView(name, state.skills.get(name)!.versions));
  });
  await page.route("**/api/skills/custom/*/undo", (route) => {
    const name = route.request().url().split("/").at(-2)!;
    const body = route.request().postDataJSON() as {
      to_version: number;
      base_version: number;
    };
    state.undos.push({ kind: "skill", name, ...body });
    const entry = state.skills.get(name)!;
    const target = entry.versions.find((v) => v.version === body.to_version)!;
    writeSkill(name, target.snapshot.content, "undo");
    return json(route, versionsView(name, entry.versions));
  });
  await page.route("**/api/skills/custom/*/files", (route) =>
    json(route, {
      skill_name: route.request().url().split("/").at(-2),
      files: [],
    }),
  );
  await page.route("**/api/skills/custom/*", (route) => {
    const name = decodeURIComponent(route.request().url().split("/").pop()!);
    if (!state.skills.has(name))
      return json(route, { detail: "Skill not found" }, 404);
    if (route.request().method() === "PUT") {
      const body = route.request().postDataJSON() as {
        content: string;
        base_version: number;
        source?: string;
      };
      const head = state.skills.get(name)!.versions.at(-1)!;
      if (body.base_version !== head.version)
        return json(
          route,
          { detail: stale("skill", name, body.base_version, head.version) },
          409,
        );
      writeSkill(name, body.content, body.source ?? "manual");
    }
    return json(route, customView(name));
  });
  // The Test route asks the model `tries` times whether it would open the
  // skill. The fake model opens it when the message shares a word with the
  // skill's "when" sentence.
  await page.route("**/api/skills/*/test", (route) => {
    try {
      return skillTest(route);
    } catch (e) {
      return json(route, { detail: `stub: ${String(e)}` }, 500);
    }
  });
  const skillTest = (route: Route) => {
    const name = route.request().url().split("/").at(-2)!;
    const body = route.request().postDataJSON() as {
      message: string;
      tries: number;
    };
    state.skillTests.push({ name, ...body });
    const when = skillDescription(
      state.skills.get(name)!.versions.at(-1)!.snapshot.content,
    ).toLowerCase();
    const words = body.message
      .toLowerCase()
      .split(/\W+/)
      .filter((w) => w.length > 3);
    const loads = words.some((w) => when.includes(w));
    const tries = Array.from({ length: body.tries }, () => ({
      loaded: loads,
      other_skills: [],
      error: null,
    }));
    return json(route, {
      skill: name,
      model: "default",
      listed: true,
      tries,
      loaded: loads ? body.tries : 0,
      total: body.tries,
    });
  };

  // ---- the ledger's projects (Overview: Works on) -----------------------
  await page.route("**/api/ledger/projects", (route) =>
    json(
      route,
      PROJECTS.map((p) => ({
        ...p,
        why: null,
        status: "active",
        context: null,
        version: 1,
        created_at: "2026-10-01T00:00:00+00:00",
        updated_at: "2026-10-01T00:00:00+00:00",
        open_tasks: 0,
        overdue: 0,
        done_tasks: 0,
      })),
    ),
  );

  // A skill the drafted agent can load.
  writeSkill(
    "cite-every-claim",
    "---\nname: cite-every-claim\ndescription: Use when stating facts.\n---\n\nCite every claim.\n",
    "manual",
  );
  return state;
}
