/**
 * Spec 011 FR-020..FR-024, FR-031: the host side of one app frame, apart from
 * React so the handshake, the checks and the teardown are unit-tested.
 *
 * - Handshake on the frame's FIRST load only: a MessageChannel, `init` posted
 *   with port 2 to the frame's own contentWindow ("*" because its origin is
 *   opaque; safe because it goes only to this frame, once).
 * - A SECOND load (the frame reloaded or navigated itself) closes the port
 *   and tears the frame down. No second handshake, ever.
 * - Everything after the handshake is accepted on the port only. Window
 *   messages are ignored, except the shim's `ready` from this frame; any
 *   other protocol-looking window message is refused and reported.
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
  isReadyMessage,
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
  reportRefusal(refusal: Refusal): void;
  openExternal(url: string): void;
  openInternal(path: string): void;
  onConnect(source: string): void;
  /** The frame loaded a second time: remove it and say so. */
  onTornDown(): void;
  now?: () => number;
  createChannel?: () => MessageChannel;
}

type Phase = "waiting" | "connected" | "torn-down" | "disposed";

export class AppHostController {
  private phase: Phase = "waiting";
  private loads = 0;
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
    if (this.loads === 1) {
      this.handshake();
      return;
    }
    this.tearDown();
  }

  /** The host window's `message` event. */
  handleWindowMessage(event: Pick<MessageEvent, "source" | "data">): void {
    if (this.phase === "disposed" || this.phase === "torn-down") return;
    const fromFrame =
      this.frame?.contentWindow != null &&
      event.source === (this.frame.contentWindow as unknown);
    if (fromFrame && isReadyMessage(event.data)) return; // liveness only
    if (!looksLikeProtocol(event.data)) return; // not ours: other code's
    this.refuse(
      {
        reason: fromFrame ? "not_on_port" : "wrong_window",
        ...labels(event.data),
      },
      false,
    );
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

  private tearDown(): void {
    this.closePort();
    this.phase = "torn-down";
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
    if (this.reports.allow()) this.opts.reportRefusal(refusal);
  }

  private handlePortMessage(event: MessageEvent): void {
    if (this.phase !== "connected") return;
    if (!this.inbound.allow()) {
      // Over the limit: answered once a second, reported once a second.
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
      } catch (err) {
        result = {
          source,
          state: "failed",
          data: null,
          fetched_at: null,
          stale: false,
          reason:
            err instanceof Error ? err.message : "Could not reach OmniHarness.",
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
