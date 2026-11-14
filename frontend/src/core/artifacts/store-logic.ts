/**
 * Spec 012 Slice 1: pure helpers for the artifact card, panel and store
 * (no React, no network), unit-tested in tests/unit/artifacts-store.test.ts.
 */
import { safeField } from "@/core/display/safe";

import type {
  ArtifactKind,
  ArtifactSummary,
  ArtifactsApiError,
  VersionOrigin,
} from "./store-api";

const KINDS = new Set<string>([
  "markdown",
  "code",
  "svg",
  "mermaid",
  "chart",
  "image",
  "file",
]);
const ID = /^[A-Za-z0-9_-]{22}$/;

export interface ArtifactBinding {
  artifactId: string;
  version: number;
  kind: ArtifactKind;
}

/**
 * The card a ToolMessage asks for: its `artifact` field must be exactly
 * `{"type":"omni_artifact","artifact_id","version","kind"}` (api.md "The
 * tool message"). Anything else (a refused call's null, another tool's
 * artifact, a malformed id) is no card.
 */
export function artifactBindingOf(message: unknown): ArtifactBinding | null {
  if (!message || typeof message !== "object") return null;
  const m = message as { type?: unknown; artifact?: unknown };
  if (m.type !== "tool") return null;
  const a = m.artifact;
  if (!a || typeof a !== "object" || Array.isArray(a)) return null;
  const r = a as Record<string, unknown>;
  if (r.type !== "omni_artifact") return null;
  const id = r.artifact_id;
  const version = r.version;
  const kind = r.kind;
  if (typeof id !== "string" || !ID.test(id)) return null;
  if (
    typeof version !== "number" ||
    !Number.isInteger(version) ||
    version < 1
  ) {
    return null;
  }
  if (typeof kind !== "string" || !KINDS.has(kind)) return null;
  return { artifactId: id, version, kind: kind as ArtifactKind };
}

/** Every card binding in a list of messages, in order (one per tool call). */
export function artifactBindingsOf(messages: unknown[]): ArtifactBinding[] {
  const out: ArtifactBinding[] = [];
  for (const m of messages) {
    const b = artifactBindingOf(m);
    if (b) out.push(b);
  }
  return out;
}

/** The side panel's selection key for a store artifact at one version. */
export const PANEL_PREFIX = "omni-artifact:";
export function panelKey(id: string, version: number): string {
  return `${PANEL_PREFIX}${id}@${version}`;
}
export function parsePanelKey(
  key: string | null,
): { id: string; version: number } | null {
  if (!key?.startsWith(PANEL_PREFIX)) return null;
  const m = /^([A-Za-z0-9_-]{22})@([0-9]{1,6})$/.exec(
    key.slice(PANEL_PREFIX.length),
  );
  if (!m) return null;
  return { id: m[1]!, version: Number(m[2]) };
}

export const KIND_WORDS: Record<ArtifactKind, string> = {
  markdown: "Document",
  code: "Code",
  svg: "SVG image",
  mermaid: "Diagram",
  chart: "Chart",
  image: "Image",
  file: "File",
};

export const ORIGIN_WORDS: Record<VersionOrigin, string> = {
  tool: "Made by the assistant",
  owner_edit: "Your edit",
  restore: "Restored",
  import: "Imported from a chat",
  duplicate: "Copied",
};

export function originWords(origin: string): string {
  return ORIGIN_WORDS[origin as VersionOrigin] ?? "Changed";
}

/** Recorded by the importer before imports had a lineage of their own. */
const LEGACY_IMPORT_SOURCE = "a file from the chat";

/** True for a file indexed from a chat's outputs (lineage `import`, or an
 * older import recorded as content with the importer's source). */
export function isImported(
  lineage: string,
  source: string | null | undefined,
): boolean {
  return (
    lineage === "import" ||
    (lineage === "content" && source === LEGACY_IMPORT_SOURCE)
  );
}

/** The lineage badge: none for the owner's own work, "Imported from its
 * chat" for a chat's output file, else the content badge with the source
 * named (as text) when known. */
export function lineageWords(
  lineage: string,
  source: string | null | undefined,
): string | null {
  if (lineage === "user") return null;
  if (isImported(lineage, source)) return "Imported from its chat";
  const named = safeField(source);
  return named
    ? `Made from content the assistant read (${named})`
    : "Made from content the assistant read";
}

/** The RAW title as the owner types it back (rename starts from it; the
 * typed delete compares against it): NFKC, invisible and control
 * characters removed, whitespace collapsed. Shown only as text. */
export function confirmText(title: string | null | undefined): string {
  return (title ?? "")
    .normalize("NFKC")
    .replace(/[\p{Cc}\p{Cf}]/gu, " ")
    .split(/\s+/)
    .filter(Boolean)
    .join(" ");
}

/** An artifact title, safe to show as text (never empty). */
export function titleText(title: string | null | undefined): string {
  return safeField(title) || "Untitled";
}

const MB = 1024 * 1024;
export const IMPORT_COPY_CAP = 10 * MB;

/** An imported file over 10 MB is not in the store: it lives in its chat. */
export function livesInChat(
  a: Pick<ArtifactSummary, "imported_from" | "size">,
) {
  return a.imported_from !== null && a.size > IMPORT_COPY_CAP;
}

export function formatBytes(n: number): string {
  if (!Number.isFinite(n) || n < 0) return "";
  if (n < 1024) return `${n} B`;
  if (n < MB) return `${(n / 1024).toFixed(n < 10 * 1024 ? 1 : 0)} KB`;
  if (n < 1024 * MB) return `${(n / MB).toFixed(n < 10 * MB ? 1 : 0)} MB`;
  return `${(n / (1024 * MB)).toFixed(2)} GB`;
}

/** Words for a write the gateway refused (api.md error codes). */
export function refusalWords(err: unknown): string {
  const e = err as Partial<ArtifactsApiError> | undefined;
  switch (e?.code) {
    case "stale_base_version":
      return "A newer version exists.";
    case "artifact_archived":
      return "This artifact is archived. Restore it first.";
    case "not_archived":
      return "Archive it first; only archived artifacts can be deleted.";
    case "confirmation_mismatch":
      return "This artifact changed since the dialog opened. Check the version count and try again.";
    case "too_large":
      return "That is larger than an artifact can be.";
    case "quota_exceeded":
      return "Your artifact store is full.";
    case "invalid_content":
      return "The gateway could not accept this content.";
    case "not_editable":
      return "This kind can't be edited here.";
    case "artifact_not_found":
      return "This artifact no longer exists.";
    case "artifacts_unavailable":
      return "Artifacts aren't available on this server.";
    default:
      return "Something went wrong. Try again in a moment.";
  }
}

/** A read that answers the same again: no retry (a missing route must cost
 * one request, not four). */
export function retryUnless4xx(count: number, error: Error): boolean {
  const status = (error as Partial<ArtifactsApiError>).status;
  if (typeof status === "number" && status >= 400 && status < 600) {
    return false;
  }
  return count < 1;
}

/** The start of a markdown artifact for a card preview, clipped only at a
 * BLOCK boundary (a blank line outside a code fence), never mid-token: a
 * clipped `**bold` or a lone setext underline would otherwise render as
 * stray characters. If even the first block is over the budget, it is cut
 * at a line boundary and an open code fence is closed. */
export function previewMarkdown(text: string, lines = 6, chars = 400): string {
  const all = text.replace(/\r\n?/g, "\n").split("\n");
  const kept: string[] = [];
  let inFence = false;
  let lastBoundary = 0;
  let used = 0;
  for (const raw of all) {
    const line = raw.replace(/[\p{Cc}\p{Cf}]/gu, "");
    if (kept.length >= lines || used + line.length > chars) break;
    if (/^\s*(```|~~~)/.test(line)) inFence = !inFence;
    kept.push(line);
    used += line.length + 1;
    if (!inFence && line.trim() === "") lastBoundary = kept.length;
  }
  const done = kept.length === all.length;
  if (done) return kept.join("\n");
  if (lastBoundary > 0) return kept.slice(0, lastBoundary).join("\n").trimEnd();
  // One long first block: cut at a line boundary, close an open fence.
  const fences = kept.filter((l) => /^\s*(```|~~~)/.test(l)).length;
  return kept.join("\n") + (fences % 2 === 1 ? "\n```" : "");
}

/** The first lines of a text artifact, as a plain-text preview. */
export function previewLines(text: string, lines = 6, chars = 400): string {
  return text
    .slice(0, chars * 2)
    .split("\n")
    .slice(0, lines)
    .map((l) => l.replace(/[\p{Cc}\p{Cf}]/gu, "").slice(0, chars))
    .join("\n");
}
