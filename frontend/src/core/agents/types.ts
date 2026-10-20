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
  /** Current version in the versioned store; send back as base_version. */
  version?: number;
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
  /** The version the edit was made from: a stale one is refused (409). */
  base_version?: number | null;
  source?: "manual" | "draft";
}
