/**
 * Spec 012 Slice 1: the gateway's artifact store routes
 * (specs/012-artifacts/api.md). Every call is the owner's own session; writes
 * carry the CSRF header (the shared fetch wrapper adds it).
 *
 * Everything an artifact carries (title, note, content) is DATA: components
 * show it as text through safeField, never as HTML.
 */
import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

export const STATIC_KINDS = [
  "markdown",
  "code",
  "svg",
  "mermaid",
  "chart",
  "image",
] as const;
export type ArtifactKind = (typeof STATIC_KINDS)[number] | "file";

/** Kinds with an owner editor in S1 (api.md, POST /versions). */
export const EDITABLE_KINDS: readonly ArtifactKind[] = [
  "markdown",
  "code",
  "mermaid",
];

/** Kinds whose version detail carries `content` inline. */
export const TEXT_KINDS: readonly ArtifactKind[] = [
  "markdown",
  "code",
  "mermaid",
  "chart",
];

export type Lineage = "user" | "content";
export type VersionOrigin =
  | "tool"
  | "owner_edit"
  | "restore"
  | "import"
  | "duplicate";

export interface ArtifactSummary {
  id: string;
  kind: ArtifactKind;
  title: string;
  latest_version: number;
  version_count: number;
  pinned: boolean;
  archived: boolean;
  archived_at: string | null;
  origin_thread_id: string | null;
  origin_turn_id: string | null;
  imported_from: string | null;
  lineage: Lineage;
  lineage_source: string | null;
  language: string | null;
  media_type: string;
  size: number;
  created_at: string;
  updated_at: string;
}

export interface ArtifactVersion {
  n: number;
  content_hash: string;
  size: number;
  media_type: string;
  language: string | null;
  lineage: Lineage;
  lineage_source: string | null;
  origin: VersionOrigin;
  base_version: number | null;
  note: string | null;
  thread_id: string | null;
  turn_id: string | null;
  tool_call_id: string | null;
  stored: "blob" | "chat";
  created_at: string;
}

export type CodeContent = { language: string; text: string };

export interface ArtifactVersionDetail extends ArtifactVersion {
  /** markdown, mermaid: string; code: {language, text}; chart: the spec
   * object; svg, image, file: null (load through the content route). */
  content: unknown;
}

export interface ArtifactDetail extends ArtifactSummary {
  versions: ArtifactVersion[];
}

export interface ThreadArtifact extends ArtifactSummary {
  versions_in_thread: {
    n: number;
    turn_id: string | null;
    tool_call_id: string | null;
    origin: VersionOrigin;
    created_at: string;
  }[];
}

export interface Usage {
  used: number;
  cap: number;
}

export interface ListQuery {
  kind?: ArtifactKind;
  pinned?: boolean;
  archived?: boolean | "all";
  thread?: string;
  q?: string;
  limit?: number;
  offset?: number;
}

/** A gateway refusal with its stable code (api.md "Error codes"). */
export class ArtifactsApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string,
    readonly extra: Record<string, unknown> = {},
  ) {
    super(message);
  }
}

const enc = encodeURIComponent;
const base = () => `${getBackendBaseURL()}/api/artifacts`;

/** The raw content of one version: images and SVG are shown ONLY as
 * `<img src>` of this URL (never inline markup). */
export function contentUrl(id: string, n: number): string {
  return `${base()}/${enc(id)}/versions/${enc(String(n))}/content`;
}

export async function readResponse<T>(response: Response): Promise<T> {
  if (response.ok) return (await response.json()) as T;
  let code = "error";
  let message = `The gateway answered ${response.status}.`;
  let extra: Record<string, unknown> = {};
  try {
    const body = (await response.json()) as {
      detail?: unknown;
    };
    const detail = body.detail;
    if (typeof detail === "string") message = detail;
    else if (detail && typeof detail === "object" && !Array.isArray(detail)) {
      const d = detail as Record<string, unknown>;
      if (typeof d.code === "string") code = d.code;
      if (typeof d.message === "string") message = d.message;
      extra = d;
    }
  } catch {
    // Not JSON: keep the status line.
  }
  throw new ArtifactsApiError(message, response.status, code, extra);
}

function send(path: string, method: "POST" | "PATCH", body?: unknown) {
  return fetch(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

export async function listArtifacts(query: ListQuery = {}): Promise<{
  artifacts: ArtifactSummary[];
  total: number;
  usage: Usage;
}> {
  const params = new URLSearchParams();
  if (query.kind) params.set("kind", query.kind);
  if (query.pinned !== undefined) params.set("pinned", String(query.pinned));
  if (query.archived !== undefined)
    params.set("archived", String(query.archived));
  if (query.thread) params.set("thread", query.thread);
  if (query.q) params.set("q", query.q);
  params.set("limit", String(query.limit ?? 200));
  if (query.offset) params.set("offset", String(query.offset));
  return readResponse(await fetch(`${base()}?${params.toString()}`));
}

export async function listThreadArtifacts(
  threadId: string,
): Promise<ThreadArtifact[]> {
  const body = await readResponse<{ artifacts: ThreadArtifact[] }>(
    await fetch(`${base()}/threads/${enc(threadId)}`),
  );
  return body.artifacts;
}

export async function getArtifact(id: string): Promise<ArtifactDetail> {
  return readResponse(await fetch(`${base()}/${enc(id)}`));
}

export async function getVersion(
  id: string,
  n: number,
): Promise<ArtifactVersionDetail> {
  return readResponse(
    await fetch(`${base()}/${enc(id)}/versions/${enc(String(n))}`),
  );
}

export async function getUsage(): Promise<Usage> {
  return readResponse(await fetch(`${base()}/usage`));
}

export async function patchArtifact(
  id: string,
  body: { title?: string; pinned?: boolean },
): Promise<ArtifactSummary> {
  return readResponse(await send(`${base()}/${enc(id)}`, "PATCH", body));
}

export async function archiveArtifact(
  id: string,
  archived: boolean,
): Promise<ArtifactSummary> {
  return readResponse(
    await send(
      `${base()}/${enc(id)}/${archived ? "archive" : "unarchive"}`,
      "POST",
    ),
  );
}

export async function saveVersion(
  id: string,
  body: { base_version: number; content: string; language?: string },
): Promise<{ artifact: ArtifactSummary; version: ArtifactVersion }> {
  return readResponse(
    await send(`${base()}/${enc(id)}/versions`, "POST", body),
  );
}

export async function restoreVersion(
  id: string,
  version: number,
  baseVersion: number,
): Promise<{ artifact: ArtifactSummary; version: ArtifactVersion }> {
  return readResponse(
    await send(`${base()}/${enc(id)}/restore`, "POST", {
      version,
      base_version: baseVersion,
    }),
  );
}

export async function duplicateArtifact(
  id: string,
  version?: number,
): Promise<ArtifactSummary> {
  return readResponse(
    await send(
      `${base()}/${enc(id)}/duplicate`,
      "POST",
      version === undefined ? {} : { version },
    ),
  );
}

export async function deleteArtifact(
  id: string,
  versionCount: number,
): Promise<{ deleted: string }> {
  return readResponse(
    await send(`${base()}/${enc(id)}/delete`, "POST", {
      confirm_id: id,
      version_count: versionCount,
    }),
  );
}
