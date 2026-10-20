import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type {
  AgentRuns,
  CustomSkill,
  SkillFiles,
  StudioOptions,
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

export const createCustomSkill = (name: string, content: string) =>
  call<CustomSkill>("/api/skills/custom", {
    method: "POST",
    body: JSON.stringify({ name, content }),
  });

export const saveCustomSkill = (name: string, content: string) =>
  call<CustomSkill>(`/api/skills/custom/${encodeURIComponent(name)}`, {
    method: "PUT",
    body: JSON.stringify({ content }),
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
