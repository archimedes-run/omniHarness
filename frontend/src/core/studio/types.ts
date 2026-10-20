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
