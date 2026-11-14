/**
 * Spec 011 FR-019..FR-023: the message protocol between the trusted host page
 * and an app's sandboxed frame. The schema is protocol.schema.json, checked
 * by validate.js, the same function the platform shim carries inline.
 *
 * This module adds what only the host can judge: whether a source is in the
 * APPROVED manifest of the served version, the rate limit, and whether a
 * link may be opened.
 */
import SCHEMA from "./protocol.schema.json";
import { validateProtocolMessage } from "./validate";

export const PROTOCOL_SCHEMA = SCHEMA;
export const MAX_FRAME_MESSAGE_BYTES = SCHEMA.limits.frame_to_host_max_bytes;
export const MAX_FRAME_MESSAGES_PER_SECOND =
  SCHEMA.limits.frame_to_host_per_second;

export type Theme = "light" | "dark";
export type SourceState = "fresh" | "empty" | "not_connected" | "failed";

export const SOURCE_STATES: readonly SourceState[] = [
  "fresh",
  "empty",
  "not_connected",
  "failed",
];

/** One source's answer, as the bridge returns it (api.md SourceResult). */
export interface SourceResult {
  source: string;
  state: SourceState;
  data: unknown;
  fetched_at: string | null;
  stale: boolean;
  reason?: string | null;
}

export type FrameMessage =
  | { v: 1; type: "data"; id: string; source: string }
  | { v: 1; type: "refresh"; id: string; source: string }
  | { v: 1; type: "open"; url: string }
  | { v: 1; type: "connect"; source: string };

export type HostMessage =
  | { v: 1; type: "init"; app: string; version: number; theme: Theme }
  | ({ v: 1; type: "result"; id: string } & SourceResult)
  | ({ v: 1; type: "update" } & SourceResult)
  | { v: 1; type: "theme"; theme: Theme }
  | { v: 1; type: "error"; id?: string | null; reason: string };

export type FrameCheck =
  | { ok: true; message: FrameMessage }
  | { ok: false; reason: string; type?: string; source?: string };

/** A short, safe label of what was refused, for the audit (≤ 32 / 64). */
function describe(raw: unknown): { type?: string; source?: string } {
  if (raw === null || typeof raw !== "object" || Array.isArray(raw)) return {};
  const r = raw as Record<string, unknown>;
  const clip = (v: unknown, n: number) =>
    typeof v === "string" ? v.replace(/[^\w.:-]/g, "?").slice(0, n) : undefined;
  return { type: clip(r.type, 32), source: clip(r.source, 64) };
}

/**
 * A message from the frame, as it arrived on the port. Schema first (shape,
 * size, plain JSON), then the approved manifest: a `data`, `refresh` or
 * `connect` naming a source the owner did not approve is refused here, before
 * any request leaves the page (the bridge refuses it too: two layers).
 */
export function checkFrameMessage(
  raw: unknown,
  approvedSources: ReadonlySet<string>,
): FrameCheck {
  const verdict = validateProtocolMessage(SCHEMA, "frame_to_host", raw);
  if (!verdict.ok)
    return { ok: false, reason: verdict.reason, ...describe(raw) };
  const message = raw as FrameMessage;
  if (message.type !== "open" && !approvedSources.has(message.source)) {
    return {
      ok: false,
      reason: "source_not_approved",
      type: message.type,
      source: message.source,
    };
  }
  return { ok: true, message };
}

/** The shim's one window message, `hello`: its nonce, or null if it is not
 * a well-formed hello. Accepted only from the app's own frame. */
export function helloNonce(raw: unknown): string | null {
  if (!validateProtocolMessage(SCHEMA, "frame_to_host_window", raw).ok) {
    return null;
  }
  return (raw as { nonce: string }).nonce;
}

/**
 * Workspace pages an app may link to (L2): where the catalog's own links
 * point (Ledger projects, coding sessions, automations, Home). Opened in
 * place, path only: the query and fragment are dropped.
 */
export const INTERNAL_LINK_PREFIXES: readonly string[] = [
  "/workspace/projects/",
  "/workspace/sessions",
  "/workspace/automations",
  "/workspace/home",
];

const STATES = new Set<string>(SOURCE_STATES);

/**
 * A host message, built field by field from what the bridge returned, so
 * nothing else the response carried (or a token, ever) can ride along, then
 * validated with the frame's own schema before it is posted (FR-023: both
 * ways). A bridge answer the schema refuses becomes a `failed` result.
 */
export function buildResult(
  kind: "result" | "update",
  source: string,
  result: Partial<SourceResult> | null | undefined,
  id?: string,
): HostMessage {
  const known = STATES.has(String(result?.state));
  const state: SourceState = known ? result!.state! : "failed";
  const reason =
    typeof result?.reason === "string" ? result.reason.slice(0, 300) : null;
  const base = {
    v: 1 as const,
    source,
    state,
    // An answer in no known state is not vouched for: its data is dropped.
    data: known ? (result?.data ?? null) : null,
    fetched_at:
      typeof result?.fetched_at === "string"
        ? result.fetched_at.slice(0, 64)
        : null,
    stale: result?.stale === true,
    reason:
      state === "failed"
        ? (reason ??
          (known
            ? "The source could not be read."
            : "OmniHarness sent an answer this page could not read."))
        : null,
  };
  const message: HostMessage =
    kind === "result"
      ? { ...base, type: "result", id: id ?? "x" }
      : { ...base, type: "update" };
  if (validateProtocolMessage(SCHEMA, "host_to_frame", message).ok) {
    return message;
  }
  const failed = {
    v: 1 as const,
    source,
    state: "failed" as const,
    data: null,
    fetched_at: null,
    stale: false,
    reason: "OmniHarness sent an answer this page could not read.",
  };
  return kind === "result"
    ? { ...failed, type: "result", id: id ?? "x" }
    : { ...failed, type: "update" };
}

/** True when a host message passes the schema (posted only if so). */
export function isValidHostMessage(message: unknown): boolean {
  return validateProtocolMessage(SCHEMA, "host_to_frame", message).ok;
}

export type OpenTarget =
  | { ok: true; kind: "external"; url: string }
  | { ok: true; kind: "internal"; path: string }
  | { ok: false; reason: string };

/**
 * FR-019: where an app's link may go. An `https` URL on a host one of the
 * app's sources declares in the catalog (`link_hosts`), opened in a new tab
 * with noopener and noreferrer; or a workspace page on the fixed list
 * (INTERNAL_LINK_PREFIXES), path only, opened in place. Nothing else: no http, no other
 * scheme, no credentials, no port, no host the catalog did not name.
 */
export function checkOpenUrl(
  raw: string,
  linkHosts: ReadonlySet<string>,
  origin: string,
): OpenTarget {
  // Control characters and backslashes are how parsers are made to disagree.
  if (/[\u0000- \u007f\\]/.test(raw)) {
    return { ok: false, reason: "url_not_allowed" };
  }
  if (raw.startsWith("/") && !raw.startsWith("//")) {
    let url: URL;
    try {
      url = new URL(raw, origin);
    } catch {
      return { ok: false, reason: "url_not_allowed" };
    }
    const path = url.pathname;
    const allowed = INTERNAL_LINK_PREFIXES.some((prefix) =>
      prefix.endsWith("/")
        ? path.startsWith(prefix) && path.length > prefix.length
        : path === prefix || path.startsWith(prefix + "/"),
    );
    if (url.origin === origin && allowed && /^[A-Za-z0-9/_-]+$/.test(path)) {
      return { ok: true, kind: "internal", path };
    }
    return { ok: false, reason: "url_not_allowed" };
  }
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    return { ok: false, reason: "url_not_allowed" };
  }
  if (
    url.protocol !== "https:" ||
    url.username !== "" ||
    url.password !== "" ||
    url.port !== "" ||
    !linkHosts.has(url.hostname.toLowerCase())
  ) {
    return { ok: false, reason: "url_not_allowed" };
  }
  return { ok: true, kind: "external", url: url.href };
}

/**
 * At most `limit` events in any `windowMs` (a sliding window): the frame's
 * 30 messages per second, and the host's own refusal reports.
 */
export class RateLimiter {
  private stamps: number[] = [];
  constructor(
    private readonly limit: number,
    private readonly windowMs = 1000,
    private readonly now: () => number = () => Date.now(),
  ) {}

  allow(): boolean {
    const t = this.now();
    while (this.stamps.length > 0 && t - this.stamps[0]! >= this.windowMs) {
      this.stamps.shift();
    }
    if (this.stamps.length >= this.limit) return false;
    this.stamps.push(t);
    return true;
  }
}
