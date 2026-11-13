import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";
import { safeField } from "@/core/display/safe";

/** What a chat is building (Spec 010 FR-003): set when the assistant calls a
 *  builder tool, cleared by the chip's ×. */
export interface Building {
  kind: "agent" | "skill" | "automation" | string;
  name: string;
  title: string;
  draft_id: string;
  /** Set once saved; the chip stays until × or a new build. */
  saved_version: number | null;
}

export interface BuilderState {
  thread_id: string;
  building: Building | null;
}

export async function loadBuilding(threadId: string): Promise<BuilderState> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}/builder`,
  );
  if (!response.ok) return { thread_id: threadId, building: null };
  const state = (await response.json()) as BuilderState;
  // The title is the model's words: made safe to display (005 Amendment 1).
  return state.building
    ? {
        ...state,
        building: {
          ...state.building,
          title: safeField(state.building.title),
          name: safeField(state.building.name),
        },
      }
    : state;
}

/** The chip's ×: drops the draft. Nothing in the config store changes. */
export async function dropBuilding(threadId: string): Promise<void> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}/builder`,
    { method: "DELETE" },
  );
  if (!response.ok)
    throw new Error(`Could not drop the draft (${response.status})`);
}
