export interface Agent {
  name: string;
  description: string;
  model: string | null;
  tool_groups: string[] | null;
  skills: string[] | null;
  soul?: string | null;
  /** Feature 006: a name for people; null shows the title-cased slug. */
  display_name?: string | null;
  /** Ledger project ids this agent works on. */
  projects?: string[] | null;
  /** 006-G: one of the agent avatars (core/agents/avatars.ts); null shows a
   * default picked from the agent's name. */
  avatar?: string | null;
  /** 006-G: per-agent integrations and tools; null keeps tool_groups. */
  tools?: AgentTools | null;
  /** 006-G: delivery defaults for the agent's new schedules. */
  notify?: AgentNotify | null;
  /** Current version in the versioned store; send back as base_version. */
  version?: number;
}

/** Mirrors AgentToolsField in app/gateway/routers/agents.py. */
export interface AgentTools {
  integrations: string[];
  tools: string[];
}

export interface AgentNotify {
  telegram: boolean;
  home: boolean;
}

export interface CreateAgentRequest {
  name: string;
  description?: string;
  model?: string | null;
  tool_groups?: string[] | null;
  skills?: string[] | null;
  soul?: string;
  display_name?: string | null;
  projects?: string[] | null;
  avatar?: string | null;
  tools?: AgentTools | null;
  notify?: AgentNotify | null;
  source?: "manual" | "draft";
}

export interface UpdateAgentRequest {
  description?: string | null;
  model?: string | null;
  tool_groups?: string[] | null;
  skills?: string[] | null;
  soul?: string | null;
  display_name?: string | null;
  projects?: string[] | null;
  avatar?: string | null;
  tools?: AgentTools | null;
  notify?: AgentNotify | null;
  /** The version the edit was made from: a stale one is refused (409). */
  base_version?: number | null;
  source?: "manual" | "draft";
}
