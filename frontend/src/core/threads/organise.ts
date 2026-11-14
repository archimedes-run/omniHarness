/**
 * Archive and folders for chats: pure helpers, unit-tested apart from the UI.
 *
 * A chat carries `archived` (boolean) and `folder` (a short label, the first
 * being "Tests") in its thread metadata, written through
 * `PATCH /api/threads/{id}`. Archiving hides a chat from Recent and Chats;
 * nothing is deleted, and it still opens by its link.
 */
import type { AgentThread } from "./types";

/** The first folder. */
export const TESTS_FOLDER = "Tests";

/** The same rule the gateway checks. */
export const FOLDER_PATTERN = /^[A-Za-z0-9][A-Za-z0-9 _-]{0,39}$/;

export interface OrganisePatch {
  archived?: boolean;
  folder?: string | null;
}

export function archivePatch(folder?: string): OrganisePatch {
  if (folder !== undefined && !FOLDER_PATTERN.test(folder)) {
    throw new Error(`Not a folder name: ${folder}`);
  }
  return folder === undefined ? { archived: true } : { archived: true, folder };
}

export function unarchivePatch(): OrganisePatch {
  return { archived: false };
}

function metaOf(
  thread: Pick<AgentThread, "metadata">,
): Record<string, unknown> {
  return thread.metadata ?? {};
}

export function isArchived(thread: Pick<AgentThread, "metadata">): boolean {
  return metaOf(thread).archived === true;
}

export function folderOf(thread: Pick<AgentThread, "metadata">): string | null {
  const folder = metaOf(thread).folder;
  return typeof folder === "string" && FOLDER_PATTERN.test(folder)
    ? folder
    : null;
}

/** Folders among these chats, sorted, "Tests" first. */
export function foldersOf(threads: Pick<AgentThread, "metadata">[]): string[] {
  const set = new Set<string>();
  for (const t of threads) {
    const f = folderOf(t);
    if (f) set.add(f);
  }
  return [...set].sort((a, b) =>
    a === TESTS_FOLDER ? -1 : b === TESTS_FOLDER ? 1 : a.localeCompare(b),
  );
}
