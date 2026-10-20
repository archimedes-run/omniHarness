import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type { Skill } from "./type";

export async function loadSkills() {
  const skills = await fetch(`${getBackendBaseURL()}/api/skills`);
  const json = await skills.json();
  return json.skills as Skill[];
}

export async function enableSkill(skillName: string, enabled: boolean) {
  const response = await fetch(
    `${getBackendBaseURL()}/api/skills/${skillName}`,
    {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        enabled,
      }),
    },
  );
  return response.json();
}

export interface InstallSkillRequest {
  thread_id: string;
  path: string;
}

export interface InstallSkillResponse {
  success: boolean;
  skill_name: string;
  message: string;
}

export async function installSkill(
  request: InstallSkillRequest,
): Promise<InstallSkillResponse> {
  const response = await fetch(`${getBackendBaseURL()}/api/skills/install`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    // Handle HTTP error responses (4xx, 5xx)
    const errorData = await response.json().catch(() => ({}));
    const errorMessage =
      errorData.detail ?? `HTTP ${response.status}: ${response.statusText}`;
    return {
      success: false,
      skill_name: "",
      message: errorMessage,
    };
  }

  return response.json();
}

/** The skills removed from one chat (GET/PUT /api/threads/{id}/skills). */
export interface ThreadSkills {
  thread_id: string;
  excluded: string[];
}

export async function getThreadSkills(threadId: string): Promise<ThreadSkills> {
  const res = await fetch(
    `${getBackendBaseURL()}/api/threads/${threadId}/skills`,
  );
  if (!res.ok) throw new Error(`get chat skills failed: ${res.status}`);
  return res.json();
}

export async function putThreadSkills(
  threadId: string,
  excluded: string[],
): Promise<ThreadSkills> {
  const res = await fetch(
    `${getBackendBaseURL()}/api/threads/${threadId}/skills`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ excluded }),
    },
  );
  if (!res.ok) throw new Error(`put chat skills failed: ${res.status}`);
  return res.json();
}
