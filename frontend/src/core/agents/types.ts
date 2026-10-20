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
}

export interface UpdateAgentRequest {
  description?: string | null;
  model?: string | null;
  tool_groups?: string[] | null;
  skills?: string[] | null;
  soul?: string | null;
  display_name?: string | null;
  projects?: string[] | null;
}
