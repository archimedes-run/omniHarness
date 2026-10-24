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
  /** Display name of the rule; "" when it has none. */
  name: string;
  /** What the firing asks the agent. */
  prompt: string;
  /** Its result is sent to Telegram (the rule's destination is auto/remote). */
  telegram: boolean;
  /** Home lists its upcoming runs and results. */
  show_on_home: boolean;
}

export interface AgentRuns {
  agent: string;
  engine_enabled: boolean;
  not_set_up_reason: "none-name-this-agent" | null;
  rules_error: string | null;
  schedules: AgentSchedule[];
  recent: FiringView[];
  /** The rule file version a schedule edit is based on (409 when stale). */
  rules_version: string | null;
  /** False when the engine runs the shipped rules, which are not edited. */
  writable: boolean;
  /** 006-G: the engine's quiet hours, when the rules file could be read. */
  quiet_hours?: QuietHoursInfo | null;
}

export interface QuietHoursInfo {
  enabled: boolean;
  /** "HH:MM", in `timezone`. */
  start: string;
  end: string;
  timezone: string;
}

/** Mirrors app/gateway/tool_catalog.py (006-G). */
export type Tier = 1 | 2 | 3;

export interface CatalogTool {
  /** The name it is offered as: what an agent's allowlist stores. */
  name: string;
  /** Without its source prefix, for display. */
  short: string;
  label: string;
  description: string;
  /** From the policy classifier; null: no rule names it (never offered). */
  tier: Tier | null;
  /** Shown while the row is collapsed. */
  common: boolean;
}

export type IntegrationKind = "app" | "mcp" | "custom" | "builtin";
export type IntegrationStatus =
  | "connected"
  | "not_connected"
  | "unreachable"
  | "disabled"
  | "not_loaded";

export interface CatalogIntegration {
  id: string;
  name: string;
  kind: IntegrationKind;
  status: IntegrationStatus;
  detail: string;
  tools: CatalogTool[];
}

export interface ToolCatalog {
  integrations: CatalogIntegration[];
  rules_error: string | null;
  connectors_available: boolean;
}

/** Mirrors app/gateway/skill_studio_store.py (006-G). */
export interface SavedSkillTest {
  message: string;
  at: string;
  model: string;
  listed: boolean;
  loaded: number;
  total: number;
  tries: { loaded: boolean; other_skills: string[]; error: string | null }[];
}

export interface SkillStudioRecord {
  icon: string | null;
  color: number | null;
  tests: SavedSkillTest[];
}

/** Mirrors ScheduleWrite in app/gateway/routers/studio.py (Feature 006-F). */
export interface ScheduleWrite {
  schedule: string;
  timezone: string;
  telegram: boolean;
  show_on_home: boolean;
  prompt?: string | null;
  name?: string | null;
  enabled?: boolean;
  version: string;
}

export interface ScheduleWritten {
  rule_id: string;
  version: string;
}

/** One sentence fills every Agent Studio tab: these are SUGGESTIONS for
 * review. A drafted grant is never ticked for the user and a drafted
 * schedule is never created (app/gateway/routers/drafts.py). */
export interface AgentDraft {
  display_name: string;
  description: string;
  instructions: string;
  tool_groups: string[];
  skills: string[];
  /** The caller's own ledger project ids (Overview: Works on). */
  projects?: string[];
  /** Grantable action-class ids it might do on its own (Autonomy). */
  autonomy?: string[];
  /** When it should run, if the sentence said (Schedule). */
  schedule?: { cron: string; timezone: string | null } | null;
  /** 006-G: integration ids it needs, from what this install has. */
  integrations?: string[];
}

/** Mirrors app/gateway/routers/drafts.py. A draft is never saved. */
export interface DraftResponse {
  kind: "agent" | "skill";
  model: string;
  agent: AgentDraft | null;
  skill: { name?: string; description: string; body: string } | null;
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
