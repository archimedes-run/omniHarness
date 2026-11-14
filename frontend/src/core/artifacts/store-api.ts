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
/** Programs (Slice 2) and imported web apps: shown ONLY in the locked frame. */
export const CODE_KINDS = ["html", "react", "webapp"] as const;
export type CodeKind = (typeof CODE_KINDS)[number];
export type ArtifactKind = (typeof STATIC_KINDS)[number] | CodeKind | "file";

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

export type Lineage = "user" | "content" | "import";
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
  /** Saved to the store by the owner. Absent on a gateway without the
   * save routes: the Save and Download controls then stay hidden. */
  saved?: boolean;
  /** Code kinds (Slice 2). */
  code?: {
    build_state?: string | null;
    check_state?: string | null;
    shown_version?: number | null;
  } | null;
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
  saved?: boolean | "all";
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
  if (query.saved !== undefined) params.set("saved", String(query.saved));
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

// -- Saving, downloading and importing (the store holds only what the
// owner saves; nothing lands in it by itself) -------------------------------

export async function setSaved(
  id: string,
  saved: boolean,
): Promise<ArtifactSummary> {
  return readResponse(
    await send(`${base()}/${enc(id)}/${saved ? "save" : "unsave"}`, "POST"),
  );
}

/** The download route of one version (an attachment); `form` picks one of
 * the kind's download forms (react: "built" or "source"). */
export function downloadUrl(id: string, n: number, form?: string): string {
  const url = `${base()}/${enc(id)}/versions/${enc(String(n))}/download`;
  return form ? `${url}?form=${enc(form)}` : url;
}

/** A file a chat produced (or a coding job's published site) saved into
 * the store: the gateway reads it from the chat's outputs by path. */
export async function importChatFile(
  threadId: string,
  path: string,
): Promise<ArtifactSummary> {
  const body = await readResponse<
    { artifact?: ArtifactSummary } & Partial<ArtifactSummary>
  >(await send(`${base()}/import`, "POST", { thread_id: threadId, path }));
  return (body.artifact ?? body) as ArtifactSummary;
}

/** The locked frame's one-view URL (Slice 2). */
export async function frameToken(
  id: string,
  n: number,
): Promise<{ token: string; expires_in: number; url: string }> {
  return readResponse(
    await fetch(`${base()}/${enc(id)}/versions/${enc(String(n))}/frame-token`),
  );
}

/** The checks' screenshot of a code version, for previews (404 if none). */
export function shotUrl(id: string, n: number, theme: "light" | "dark") {
  return `${base()}/${enc(id)}/versions/${enc(String(n))}/shots/${theme}.png`;
}
