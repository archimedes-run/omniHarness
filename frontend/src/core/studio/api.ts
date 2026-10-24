import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type {
  AgentRuns,
  AutonomyView,
  GrantUse,
  ScheduleWrite,
  ScheduleWritten,
  SkillTestResult,
  CustomSkill,
  DraftResponse,
  SkillFiles,
  SkillStudioRecord,
  StudioOptions,
  ToolCatalog,
  Versions,
} from "./types";

/** The gateway's reason, shown inline. */
export class StudioError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${getBackendBaseURL()}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as {
      detail?: unknown;
    };
    const detail =
      typeof body.detail === "string"
        ? body.detail
        : `${response.status} ${response.statusText}`;
    throw new StudioError(detail, response.status);
  }
  return response.json() as Promise<T>;
}

export const loadStudioOptions = () =>
  call<StudioOptions>("/api/studio/options");

export const loadCustomSkill = (name: string) =>
  call<CustomSkill>(`/api/skills/custom/${encodeURIComponent(name)}`);

export const createCustomSkill = (
  name: string,
  content: string,
  source: "manual" | "draft" = "manual",
) =>
  call<CustomSkill>("/api/skills/custom", {
    method: "POST",
    body: JSON.stringify({ name, content, source }),
  });

export const saveCustomSkill = (
  name: string,
  content: string,
  baseVersion: number,
  source: "manual" | "draft" = "manual",
) =>
  call<CustomSkill>(`/api/skills/custom/${encodeURIComponent(name)}`, {
    method: "PUT",
    body: JSON.stringify({ content, base_version: baseVersion, source }),
  });

export const loadSkillFiles = (name: string) =>
  call<SkillFiles>(`/api/skills/custom/${encodeURIComponent(name)}/files`);

export const addSkillFile = (name: string, path: string, content: string) =>
  call<SkillFiles>(`/api/skills/custom/${encodeURIComponent(name)}/files`, {
    method: "POST",
    body: JSON.stringify({ path, content }),
  });

export const loadAgentRuns = (name: string) =>
  call<AgentRuns>(`/api/studio/agents/${encodeURIComponent(name)}/runs`);

const schedulesPath = (name: string) =>
  `/api/studio/agents/${encodeURIComponent(name)}/schedules`;

/** A schedule IS a trigger rule that runs as this agent (Feature 006-F),
 * written through the Automations write path; owner only. */
export const createSchedule = (name: string, body: ScheduleWrite) =>
  call<ScheduleWritten>(schedulesPath(name), {
    method: "POST",
    body: JSON.stringify(body),
  });

export const updateSchedule = (
  name: string,
  ruleId: string,
  body: ScheduleWrite,
) =>
  call<ScheduleWritten>(
    `${schedulesPath(name)}/${encodeURIComponent(ruleId)}`,
    { method: "PUT", body: JSON.stringify(body) },
  );

export const deleteSchedule = (name: string, ruleId: string, version: string) =>
  call<ScheduleWritten>(
    `${schedulesPath(name)}/${encodeURIComponent(ruleId)}?version=${encodeURIComponent(version)}`,
    { method: "DELETE" },
  );

/** One sentence in, the large fields out, for review. Never saves. */
export const draft = (
  kind: "agent" | "skill",
  body: {
    sentence: string;
    agent_name?: string | null;
    name?: string | null;
    body?: string | null;
  },
) =>
  call<DraftResponse>(`/api/drafts/${kind}`, {
    method: "POST",
    body: JSON.stringify(body),
  });

const versionsPath = (kind: "agent" | "skill", name: string) =>
  kind === "agent"
    ? `/api/agents/${encodeURIComponent(name)}`
    : `/api/skills/custom/${encodeURIComponent(name)}`;

export const loadVersions = (kind: "agent" | "skill", name: string) =>
  call<Versions>(`${versionsPath(kind, name)}/versions`);

/** Restore `toVersion` as a new version; refused (409) when `baseVersion` is stale. */
export const undoTo = (
  kind: "agent" | "skill",
  name: string,
  toVersion: number,
  baseVersion: number,
) =>
  call<Versions>(`${versionsPath(kind, name)}/undo`, {
    method: "POST",
    body: JSON.stringify({ to_version: toVersion, base_version: baseVersion }),
  });

export const loadAutonomy = (name: string) =>
  call<AutonomyView>(`/api/studio/agents/${encodeURIComponent(name)}/autonomy`);

/** Grant exactly `granted` (revoking the rest), as a new agent version. */
export const saveAutonomy = (
  name: string,
  granted: string[],
  baseVersion: number,
) =>
  call<AutonomyView>(
    `/api/studio/agents/${encodeURIComponent(name)}/autonomy`,
    {
      method: "PUT",
      body: JSON.stringify({ granted, base_version: baseVersion }),
    },
  );

export const loadGrantUses = (name: string) =>
  call<GrantUse[]>(`/api/studio/agents/${encodeURIComponent(name)}/grant-uses`);

/** Ask the model a few times whether this message makes it load the skill.
 * Each try is a model call; run only when the user presses Test. */
export const testSkill = (
  name: string,
  message: string,
  tries = 3,
  save = false,
) =>
  call<SkillTestResult>(`/api/skills/${encodeURIComponent(name)}/test`, {
    method: "POST",
    body: JSON.stringify({ message, tries, save }),
  });

/** Every integration and tool an agent could be given, each with its tier
 * from the policy classifier (006-G). Owner only. */
export const loadToolCatalog = () =>
  call<ToolCatalog>("/api/studio/tool-catalog");

const skillStudioPath = (name: string) =>
  `/api/skills/custom/${encodeURIComponent(name)}/studio`;

/** A skill's icon, colour and saved test results (006-G). */
export const loadSkillStudio = (name: string) =>
  call<SkillStudioRecord>(skillStudioPath(name));

export const saveSkillAppearance = (
  name: string,
  icon: string | null,
  color: number | null,
) =>
  call<SkillStudioRecord>(skillStudioPath(name), {
    method: "PUT",
    body: JSON.stringify({ icon, color }),
  });

export const removeSkillTest = (name: string, message: string) =>
  call<SkillStudioRecord>(
    `/api/skills/custom/${encodeURIComponent(name)}/tests?message=${encodeURIComponent(message)}`,
    { method: "DELETE" },
  );

/** Remove one of a custom skill's files, as a new version (006-G). */
export const removeSkillFile = (name: string, path: string) =>
  call<SkillFiles>(
    `/api/skills/custom/${encodeURIComponent(name)}/files?path=${encodeURIComponent(path)}`,
    { method: "DELETE" },
  );

/** The IM channels' state (Telegram's "Connected" pill on Notifications). */
export const loadChannels = () =>
  call<{
    service_running: boolean;
    channels: Record<string, { enabled?: boolean; running?: boolean }>;
  }>("/api/channels/");
