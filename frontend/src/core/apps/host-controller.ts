/**
 * Spec 011 FR-020..FR-024, FR-031: the host side of one app frame, apart from
 * React so the handshake, the checks and the teardown are unit-tested.
 *
 * - The handshake is bound to ONE app document. The frame URL carries a
 *   per-open nonce (in the fragment, so the immutable cache still hits); the
 *   shim, the first script of every app document, posts `hello` with it at
 *   once, before any app code runs. The host sends `init` (a MessageChannel,
 *   port 2 to the frame's own contentWindow; "*" because its origin is
 *   opaque) only when it has seen exactly one hello with this nonce AND
 *   exactly one load, in either order, and nothing else for a short settle.
 * - Why that binds it: the frame can only ever show documents under
 *   /api/apps/ (the host page's path-scoped frame-src), and every app
 *   document there starts with the shim. A document that replaces the app
 *   document (location.replace during parse, which gives one load event)
 *   therefore either says hello too (a second hello: torn down), or runs no
 *   script at all (a JSON route or an error page: the port is harmless).
 * - A second load, a second hello, a wrong nonce, or no hello closes the
 *   port and tears the frame down. No second handshake, ever.
 * - Everything after the handshake is accepted on the port only. Window
 *   messages from the frame other than its hello are refused and reported;
 *   messages from other windows are dropped, unreported (they are not the
 *   app's doing).
 * - Each port message: at most 30 per second, schema-checked, its source in
 *   the APPROVED manifest; a refusal is answered `{type:"error", reason}` and
 *   reported to the gateway (`app_message_refused`).
 * - `data` is answered from the batch prefetch when it has the source,
 *   otherwise from the bridge; `refresh` always asks the bridge.
 */
import {
  buildResult,
  checkFrameMessage,
  checkOpenUrl,
  helloNonce,
  isValidHostMessage,
  MAX_FRAME_MESSAGES_PER_SECOND,
  RateLimiter,
  type HostMessage,
  type SourceResult,
  type Theme,
} from "./protocol";

export interface FrameLike {
  readonly contentWindow: Pick<Window, "postMessage"> | null;
}

export interface Refusal {
  reason: string;
  type?: string;
  source?: string;
}

export interface HostControllerOptions {
  appId: string;
  version: number;
  /** Source names of the served version, only when its hash is approved. */
  approvedSources: readonly string[];
  /** Hosts the approved sources' catalog entries declare for links. */
  linkHosts: readonly string[];
  /** This page's origin (for /workspace/... links). */
  origin: string;
  theme: Theme;
  /** The batch `GET /api/apps/{id}/data`, started with the frame (FR-031). */
  prefetch: Promise<Record<string, SourceResult> | null> | null;
  /** One source from the bridge; `refresh` asks for a refetch. */
  fetchSource(source: string, refresh: boolean): Promise<SourceResult>;
  /** To the gateway's audit (`app_message_refused`): codes only, never
   * free text from the frame (api.md, POST /refused). */
  reportRefusal(refusal: Refusal): void;
  openExternal(url: string): void;
  openInternal(path: string): void;
  onConnect(source: string): void;
  /** The frame loaded a second time: remove it and say so. */
  onTornDown(): void;
  now?: () => number;
  createChannel?: () => MessageChannel;
  /** Per-open nonce put in the frame URL (tests pass their own). */
  nonce?: string;
  /** How long to wait for the hello after the load (or the reverse). */
  helloGraceMs?: number;
  /** Quiet time after hello + load before init (a second hello cancels). */
  settleMs?: number;
  /** After the Connect sheet closes, `connect` is ignored this long. */
  connectCooldownMs?: number;
}

/** 128 random bits, base64url. */
export function newNonce(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  let text = "";
  for (const b of bytes) text += String.fromCharCode(b);
  return btoa(text).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

type Phase = "waiting" | "connected" | "torn-down" | "disposed";

export class AppHostController {
  private phase: Phase = "waiting";
  private loads = 0;
  private hellos = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private connectOpen = false;
  private connectClosedAt = -Infinity;
  private readonly now: () => number;
  readonly nonce: string;
  private port: MessagePort | null = null;
  private frame: FrameLike | null = null;
  private theme: Theme;
  private readonly approved: Set<string>;
  private readonly linkHosts: Set<string>;
  private readonly inbound: RateLimiter;
  private readonly reports: RateLimiter;
  private readonly answeredRateLimit: RateLimiter;
  /** Host → frame messages actually posted (tests read it). */
  readonly sent: HostMessage[] = [];

  constructor(private readonly opts: HostControllerOptions) {
    this.theme = opts.theme;
    this.approved = new Set(opts.approvedSources);
    this.linkHosts = new Set(opts.linkHosts.map((h) => h.toLowerCase()));
    const now = opts.now ?? (() => Date.now());
    this.now = now;
    this.nonce = opts.nonce ?? newNonce();
    this.inbound = new RateLimiter(MAX_FRAME_MESSAGES_PER_SECOND, 1000, now);
    // A flood is reported, not every message of it: the audit is not a
    // second channel for the frame to fill.
    this.reports = new RateLimiter(10, 1000, now);
    this.answeredRateLimit = new RateLimiter(1, 1000, now);
  }

  get state(): Phase {
    return this.phase;
  }

  attach(frame: FrameLike): void {
    this.frame = frame;
  }

  /** The iframe's `load` event. */
  handleLoad(): void {
    if (this.phase === "disposed" || this.phase === "torn-down") return;
    this.loads += 1;
    if (this.loads > 1) {
      this.tearDown("second_load");
      return;
    }
    this.progress();
  }

  /** The Connect sheet closed: `connect` is ignored for a while. */
  connectClosed(): void {
    this.connectOpen = false;
    this.connectClosedAt = this.now();
  }

  /** Hello and load seen once each: init after a settle; else wait, bounded. */
  private progress(): void {
    this.clearTimer();
    if (this.phase !== "waiting") return;
    if (this.loads === 1 && this.hellos === 1) {
      this.timer = setTimeout(() => {
        this.timer = null;
        if (this.phase === "waiting") this.handshake();
      }, this.opts.settleMs ?? 50);
      return;
    }
    this.timer = setTimeout(() => {
      this.timer = null;
      if (this.phase === "waiting") this.tearDown("no_hello");
    }, this.opts.helloGraceMs ?? 1500);
  }

  private clearTimer(): void {
    if (this.timer !== null) clearTimeout(this.timer);
    this.timer = null;
  }

  /** The host window's `message` event. */
  handleWindowMessage(event: Pick<MessageEvent, "source" | "data">): void {
    if (this.phase === "disposed" || this.phase === "torn-down") return;
    const fromFrame =
      this.frame?.contentWindow != null &&
      event.source === (this.frame.contentWindow as unknown);
    if (!fromFrame) return; // another window: not the app's doing (L1)
    const nonce = helloNonce(event.data);
    if (nonce !== null) {
      if (nonce !== this.nonce) {
        this.tearDown("bad_nonce");
        return;
      }
      this.hellos += 1;
      if (this.hellos > 1 || this.phase !== "waiting") {
        // A second app document in this frame: never hand it the port.
        this.tearDown("second_document");
        return;
      }
      this.progress();
      return;
    }
    if (!looksLikeProtocol(event.data)) return;
    this.refuse({ reason: "not_on_port", ...labels(event.data) }, false);
  }

  setTheme(theme: Theme): void {
    if (theme === this.theme) return;
    this.theme = theme;
    this.post({ v: 1, type: "theme", theme });
  }

  /** A source refreshed outside a frame request (poll, after Connect). */
  pushUpdate(source: string, result: SourceResult | null): void {
    if (!this.approved.has(source)) return;
    this.post(buildResult("update", source, result));
  }

  dispose(): void {
    this.clearTimer();
    this.closePort();
    this.phase = "disposed";
  }

  private handshake(): void {
    const target = this.frame?.contentWindow;
    if (!target) return;
    const channel = this.opts.createChannel?.() ?? new MessageChannel();
    this.port = channel.port1;
    this.port.onmessage = (event) => this.handlePortMessage(event);
    this.phase = "connected";
    const init: HostMessage = {
      v: 1,
      type: "init",
      app: this.opts.appId,
      version: this.opts.version,
      theme: this.theme,
    };
    if (!isValidHostMessage(init)) {
      this.closePort();
      this.phase = "torn-down";
      this.opts.onTornDown();
      return;
    }
    this.sent.push(init);
    target.postMessage(init, "*", [channel.port2]);
  }

  private tearDown(reason: string): void {
    this.clearTimer();
    this.closePort();
    this.phase = "torn-down";
    if (this.reports.allow()) this.opts.reportRefusal({ reason });
    this.opts.onTornDown();
  }

  private closePort(): void {
    if (this.port) {
      this.port.onmessage = null;
      this.port.close();
      this.port = null;
    }
  }

  private post(message: HostMessage): void {
    if (this.phase !== "connected" || !this.port) return;
    if (!isValidHostMessage(message)) return;
    this.sent.push(message);
    this.port.postMessage(message);
  }

  private refuse(refusal: Refusal, answer: boolean, id?: string): void {
    if (answer) {
      this.post({
        v: 1,
        type: "error",
        id: id ?? null,
        reason: refusal.reason.slice(0, 300),
      });
    }
    if (this.reports.allow()) this.opts.reportRefusal(reportOf(refusal));
  }

  private handlePortMessage(event: MessageEvent): void {
    if (this.phase !== "connected") return;
    if (!this.inbound.allow()) {
      // Over the limit: dropped (any port it carried closed), answered once
      // a second, reported once a second.
      for (const p of event.ports ?? []) p.close();
      if (this.answeredRateLimit.allow()) {
        this.refuse({ reason: "rate_limited", ...labels(event.data) }, true);
      }
      return;
    }
    if (event.ports && event.ports.length > 0) {
      for (const p of event.ports) p.close();
      this.refuse({ reason: "transfer_refused", ...labels(event.data) }, true);
      return;
    }
    const check = checkFrameMessage(event.data, this.approved);
    if (!check.ok) {
      const id = idOf(event.data);
      this.refuse(
        { reason: check.reason, type: check.type, source: check.source },
        true,
        id,
      );
      return;
    }
    const message = check.message;
    switch (message.type) {
      case "data":
        void this.answer(message.id, message.source, false);
        return;
      case "refresh":
        void this.answer(message.id, message.source, true);
        return;
      case "connect":
        // One sheet at a time, and a pause after it closes: a frame cannot
        // keep throwing the sheet up (L3).
        if (
          this.connectOpen ||
          this.now() - this.connectClosedAt <
            (this.opts.connectCooldownMs ?? 30_000)
        ) {
          this.post({ v: 1, type: "error", id: null, reason: "connect_busy" });
          return;
        }
        this.connectOpen = true;
        this.opts.onConnect(message.source);
        return;
      case "open": {
        const target = checkOpenUrl(
          message.url,
          this.linkHosts,
          this.opts.origin,
        );
        if (!target.ok) {
          this.refuse({ reason: target.reason, type: "open" }, true);
          return;
        }
        if (target.kind === "external") this.opts.openExternal(target.url);
        else this.opts.openInternal(target.path);
        return;
      }
    }
  }

  private async answer(id: string, source: string, refresh: boolean) {
    let result: SourceResult | null = null;
    if (!refresh && this.opts.prefetch) {
      try {
        const batch = await this.opts.prefetch;
        result = batch?.[source] ?? null;
      } catch {
        result = null;
      }
    }
    if (!result) {
      try {
        result = await this.opts.fetchSource(source, refresh);
      } catch {
        // A fixed string: nothing from the error (or the gateway's message)
        // is handed to the frame (L4).
        result = {
          source,
          state: "failed",
          data: null,
          fetched_at: null,
          stale: false,
          reason: "OmniHarness could not read this source just now.",
        };
      }
    }
    this.post(buildResult("result", source, result, id));
  }
}

function looksLikeProtocol(data: unknown): boolean {
  if (data === null || typeof data !== "object" || Array.isArray(data)) {
    return false;
  }
  const d = data as Record<string, unknown>;
  return d.v === 1 && typeof d.type === "string";
}

function labels(data: unknown): { type?: string; source?: string } {
  if (data === null || typeof data !== "object" || Array.isArray(data)) {
    return {};
  }
  const d = data as Record<string, unknown>;
  const clip = (v: unknown, n: number) =>
    typeof v === "string" ? v.replace(/[^\w.:-]/g, "?").slice(0, n) : undefined;
  return { type: clip(d.type, 32), source: clip(d.source, 64) };
}

function idOf(data: unknown): string | undefined {
  if (data === null || typeof data !== "object") return undefined;
  const id = (data as Record<string, unknown>).id;
  return typeof id === "string" && /^[A-Za-z0-9_-]{1,64}$/.test(id)
    ? id
    : undefined;
}

const NAME = /^[a-z][a-z0-9_]{0,31}$/;

/**
 * The audit entry for a refusal: a code from a fixed set (the frame's own
 * words never reach the log), and its type and source only when each is a
 * valid name. The frame itself is told the detailed reason.
 */
export function reportOf(refusal: Refusal): Refusal {
  const r = refusal.reason;
  const reason =
    r === "too_large"
      ? "oversized"
      : r === "not_an_object" ||
          r === "not_json" ||
          r.startsWith("unknown_key:") ||
          r.startsWith("missing_key:") ||
          r.startsWith("bad_value:")
        ? "invalid_message"
        : /^[a-z][a-z0-9_]{0,47}$/.test(r)
          ? r
          : "invalid_message";
  const out: Refusal = { reason };
  if (refusal.type && NAME.test(refusal.type)) out.type = refusal.type;
  if (refusal.source && NAME.test(refusal.source)) out.source = refusal.source;
  return out;
}
