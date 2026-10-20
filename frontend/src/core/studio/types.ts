import type { FiringView } from "@/core/triggers/types";

/** Mirrors app/gateway/routers/studio.py and the skills router's custom-skill
 * routes (Feature 006, Phase 3). */

export interface StudioOptions {
  tool_groups: string[];
  default_model: string | null;
}

export interface CustomSkill {
  name: string;
  description: string;
  category: string;
  enabled: boolean;
  /** The whole SKILL.md, frontmatter included. */
  content: string;
  /** Current version in the versioned store; send back as base_version. */
  version: number;
}

export interface SkillFile {
  path: string;
  size: number;
}

export interface SkillFiles {
  skill_name: string;
  files: SkillFile[];
}

/** Mirrors app/gateway/agent_runs_view.py. */
export interface AgentSchedule {
  rule_id: string;
  schedule: string;
  timezone: string;
  /** False: the rule names no zone and runs on the engine's clock (UTC). */
  timezone_named: boolean;
  enabled: boolean;
  next_run: string | null;
  held_until: string | null;
  error: string | null;
}

export interface AgentRuns {
  agent: string;
  engine_enabled: boolean;
  not_set_up_reason: "none-name-this-agent" | null;
  rules_error: string | null;
  schedules: AgentSchedule[];
  recent: FiringView[];
}

/** Mirrors app/gateway/routers/drafts.py. A draft is never saved. */
export interface DraftResponse {
  kind: "agent" | "skill";
  model: string;
  agent: {
    display_name: string;
    description: string;
    instructions: string;
    tool_groups: string[];
    skills: string[];
  } | null;
  skill: { description: string; body: string } | null;
  dropped: string[];
}

/** Mirrors the /versions routes of the agents and skills APIs. */
export interface VersionSummary {
  version: number;
  at: string;
  /** "user:<id>", "agent:<name>", "agent", or "unknown". */
  who: string;
  source: "manual" | "draft" | "proposal" | "chat" | "undo" | "existing";
  changed: string[];
  deleted: boolean;
}

export interface Versions {
  name: string;
  current: number;
  versions: VersionSummary[];
}

/** Mirrors the autonomy routes of app/gateway/routers/studio.py. */
export interface ActionClassView {
  id: string;
  label: string;
  /** What it lets the agent do, in plain words. */
  allows: string;
  granted: boolean;
  grantable: boolean;
  not_grantable_reason: string;
}

export interface AutonomyView {
  agent: string;
  version: number;
  classes: ActionClassView[];
  cap_per_run: number;
  always_waits: string[];
  rules_error: string | null;
}

export interface GrantUse {
  at: string;
  tool: string;
  classes: string[];
  targets: string[];
  thread_id: string | null;
  rule_id: string | null;
  origin: "automation" | "content" | "unknown" | string;
  origin_source: string;
  count_in_run: number;
}

/** Mirrors SkillTestResponse in app/gateway/routers/skills.py. */
export interface SkillTestResult {
  skill: string;
  model: string;
  listed: boolean;
  tries: { loaded: boolean; other_skills: string[]; error: string | null }[];
  loaded: number;
  total: number;
}
