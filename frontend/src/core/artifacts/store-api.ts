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
/** Slice 2: programs, shown ONLY in the locked frame (artifact-frame.tsx). */
export const CODE_KINDS = ["html", "react", "webapp"] as const;
export type CodeKind = (typeof CODE_KINDS)[number];
export type ArtifactKind = (typeof STATIC_KINDS)[number] | CodeKind | "file";

export function isCodeKind(kind: ArtifactKind): kind is CodeKind {
  return kind === "html" || kind === "react" || kind === "webapp";
}

/** Kinds with an owner editor (api.md, POST /versions); react is rebuilt. */
export const EDITABLE_KINDS: readonly ArtifactKind[] = [
  "markdown",
  "code",
  "mermaid",
  "html",
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
  /** Saved by the owner (the Saved tab lists only these). */
  saved: boolean;
  saved_at: string | null;
  /** Its chat was deleted; the artifact is kept and still opens. */
  origin_deleted: boolean;
  /** Code kinds only (api.md "Code kinds"). */
  code?: CodeSummary;
}

export type CheckState = "pending" | "passed" | "failed" | "not_checked";

export interface CodeSummary {
  build_state: "ok" | "build_failed" | null;
  check_state: CheckState | null;
  /** The newest version that built: what a card shows. */
  shown_version: number | null;
  build: {
    state: "running" | "done" | "failed" | "interrupted";
    base_version: number;
    reason: string | null;
    result_version: number | null;
    started_at: string;
  } | null;
}

export interface CheckInfo {
  state: CheckState;
  /** The system's words. */
  summary: string[];
  /** May carry the page's own names: text only. */
  failures: string[];
  warnings: string[];
  widths?: number[];
  themes?: string[];
  shots: { light: boolean; dark: boolean };
  checked_at: string | null;
}

export interface CodeVersionInfo {
  build_state: "ok" | "build_failed";
  has_source: boolean;
  findings: string[];
  fix_of: number | null;
  recipe: Record<string, unknown> | null;
  check: CheckInfo | null;
}

export interface ReactSource {
  entry: string;
  files: Record<string, string>;
}

/** How the store shows a version (api.md "Rendering in the store"). */
export type RenderTarget =
  | "markdown"
  | "code"
  | "image"
  | "mermaid"
  | "chart"
  | "text"
  | "download"
  | "frame";

export interface ArtifactVersion {
  /** Set by the gateway on every version it describes. */
  render?: RenderTarget | null;
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
  code?: CodeVersionInfo | null;
}

export type CodeContent = { language: string; text: string };

export interface ArtifactVersionDetail extends ArtifactVersion {
  /** markdown, mermaid: string; code: {language, text}; chart: the spec
   * object; svg, image, file: null (load through the content route). */
  content: unknown;
  /** webapp: its entry page and file list. */
  /** webapp (the save model): its entry, files, and pages prepared at save. */
  entry?: string;
  files?: { path: string; size: number; media_type: string }[];
  pages?: { path: string; ok: boolean; reason: string | null }[];
  /** react: the {entry, files} source. */
  source?: ReactSource | null;
  /** A failed build's log tail (the compiler's words: text only). */
  build_log?: string | null;
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

// -- Saving and saving a chat's output (the store holds only what the
// owner saves; nothing lands in it by itself; api.md "Saved and unsaved") ---

/** Save or unsave (unsave also unpins). Idempotent. */
export async function setSaved(
  id: string,
  saved: boolean,
): Promise<ArtifactSummary> {
  return readResponse(
    await send(`${base()}/${enc(id)}/${saved ? "save" : "unsave"}`, "POST"),
  );
}

export interface ImportResult {
  artifact: ArtifactSummary;
  /** False when the same path with the same content was saved before. */
  created: boolean;
  /** Entries of a web app directory that were left out (at most 200). */
  skipped: string[];
}

/** "Save to artifacts" on a chat's output file or web app directory: a
 * SAVED artifact read by the gateway from the chat's outputs by path. */
export async function importChatFile(
  threadId: string,
  path: string,
): Promise<ImportResult> {
  return readResponse(
    await send(`${base()}/import`, "POST", { thread_id: threadId, path }),
  );
}

// -- Slice 2: the locked frame and code kinds -------------------------------------

/** A short-lived token for ONE view of one version's frame. */
export async function getFrameToken(
  id: string,
  n: number,
): Promise<{ token: string; expires_in: number; url: string }> {
  return readResponse(
    await fetch(`${base()}/${enc(id)}/versions/${enc(String(n))}/frame-token`),
  );
}

/** A code version to keep (always an attachment): the built page (.html,
 * with a network-blocking CSP meta tag) or its sources (.zip). */
export function downloadUrl(id: string, n: number, form: "page" | "source") {
  const url = `${base()}/${enc(id)}/versions/${enc(String(n))}/download`;
  return form === "source" ? `${url}?source=zip` : url;
}

/** The checks' own screenshot (1280 px) for previews: shown as <img> only. */
export function shotUrl(id: string, n: number, theme: "light" | "dark") {
  return `${base()}/${enc(id)}/versions/${enc(String(n))}/shots/${theme}.png`;
}

export async function rebuildArtifact(
  id: string,
  body: { base_version: number; content: ReactSource },
): Promise<{ build: CodeSummary["build"] }> {
  return readResponse(await send(`${base()}/${enc(id)}/rebuild`, "POST", body));
}

export async function checkAgain(
  id: string,
  n: number,
): Promise<{ state: CheckState }> {
  return readResponse(
    await send(`${base()}/${enc(id)}/versions/${enc(String(n))}/check`, "POST"),
  );
}

/** A frame message the host dropped (codes only; api.md POST /refused). */
export function reportFrameRefusal(
  id: string,
  refusal: { reason: string; type?: string },
): void {
  void send(`${base()}/${enc(id)}/refused`, "POST", refusal).catch(
    () => undefined,
  );
}
