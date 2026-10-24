import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type {
  Goal,
  Link,
  Note,
  Project,
  ProjectSummary,
  ProjectView,
  Task,
} from "./types";

/** The ledger's reason, shown inline. A stale edit (409) carries the row as
 * it now is, so the page can show what changed. */
export class LedgerError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly current?: unknown,
  ) {
    super(message);
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${getBackendBaseURL()}/api/ledger${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as {
      detail?: string | { message?: string; current?: unknown };
    };
    const detail = body.detail;
    if (typeof detail === "object" && detail) {
      throw new LedgerError(
        detail.message ?? "That did not work.",
        response.status,
        detail.current,
      );
    }
    throw new LedgerError(
      typeof detail === "string" ? detail : `HTTP ${response.status}`,
      response.status,
    );
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

const send = (method: string, body?: unknown): RequestInit => ({
  method,
  body: body === undefined ? undefined : JSON.stringify(body),
});

export const listProjects = () => call<ProjectSummary[]>("/projects");
export const loadProject = (id: string) => call<ProjectView>(`/projects/${id}`);
export const createProject = (body: { name: string; why?: string }) =>
  call<Project>("/projects", send("POST", body));
export const patchProject = (
  id: string,
  body: Partial<Pick<Project, "name" | "why" | "status" | "context">> & {
    version: number;
  },
) => call<Project>(`/projects/${id}`, send("PATCH", body));

export const createGoal = (
  projectId: string,
  body: { title: string; definition_of_done: string; target_date?: string },
) => call<Goal>(`/projects/${projectId}/goals`, send("POST", body));

export const createTask = (
  projectId: string,
  body: { title: string; due_date?: string; owner?: string; goal_id?: string },
) => call<Task>(`/projects/${projectId}/tasks`, send("POST", body));
export const patchTask = (
  id: string,
  body: {
    version: number;
    title?: string;
    status?: Task["status"];
    due_date?: string;
    owner?: string;
    clear?: ("due_date" | "owner" | "goal_id")[];
  },
) => call<Task>(`/tasks/${id}`, send("PATCH", body));

export const createNote = (
  projectId: string,
  body: { decided: string; why?: string },
) => call<Note>(`/projects/${projectId}/notes`, send("POST", body));

export const attachThread = (
  projectId: string,
  threadId: string,
  label?: string,
) =>
  call<Link>(
    "/links",
    send("POST", {
      project_id: projectId,
      to_kind: "thread",
      to_ref: threadId,
      label,
    }),
  );
export const detachLink = (linkId: string) =>
  call<void>(`/links/${linkId}`, send("DELETE"));
export const threadProjects = (threadId: string) =>
  call<{ link_id: string; project: Project }[]>(
    `/threads/${threadId}/projects`,
  );
export const promoteTodos = (body: {
  thread_id: string;
  project_id: string;
  titles: string[];
}) => call<Task[]>("/tasks/promote", send("POST", body));

/** Undo a ledger write the assistant made without asking (005 FR-009
 * Amendment 1): its disclosure names the write id. */
export const undoWrite = (writeId: string) =>
  call<{ write_id: string; undone: string[] }>(
    `/writes/${encodeURIComponent(writeId)}/undo`,
    send("POST"),
  );

const UNDO_MARK = /\s*\[undo (w-[0-9a-f]+)\]\s*$/;

/** A ledger_apply result's text and, when it was a write made without
 * asking, the id its Undo reverts. */
export function parseLedgerResult(result: string): {
  text: string;
  writeId: string | null;
} {
  const match = UNDO_MARK.exec(result);
  return match
    ? { text: result.replace(UNDO_MARK, ""), writeId: match[1] ?? null }
    : { text: result, writeId: null };
}
