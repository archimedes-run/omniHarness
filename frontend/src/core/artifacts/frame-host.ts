/**
 * Spec 012 FR-016, FR-019: the host side of one locked artifact frame, apart
 * from React so the handshake and the checks are unit-tested. The pattern is
 * the Apps host controller's (core/apps/host-controller.ts), minus all data:
 * an artifact frame gets no bridge, no token and no data, only its theme.
 *
 * - The frame URL carries a per-view nonce in the fragment. The gateway's
 *   shim, the first script of every artifact document, posts `hello` with it
 *   to the parent. The host sends `init` (a MessageChannel, port 2 to the
 *   frame's own contentWindow; "*" because its origin is opaque) only after
 *   exactly one hello with this nonce AND exactly one load, then a short
 *   settle. A second load or hello, a wrong nonce or no hello tears the frame
 *   down (no second handshake, ever).
 * - Window messages: only from this frame's contentWindow (event.source), and
 *   only the hello. Anything else from the frame is refused and reported;
 *   messages from other windows are ignored.
 * - On the port, exactly: `ready`, `size {height}` (clamped 120..1200),
 *   `open {url}` (https only; the host asks the owner first). Each a plain
 *   object with exactly its keys, at most 30 per second; transferred ports
 *   are closed. Anything else is dropped and reported (codes only).
 * - Nothing a frame sends reaches the model, a tool or a card.
 */

export type FrameTheme = "light" | "dark";

export const SIZE_MIN = 120;
export const SIZE_MAX = 1200;
export const MAX_MESSAGES_PER_SECOND = 30;
const VAR_NAME = /^--[a-z0-9-]{1,48}$/;
const VAR_VALUE = /^[#a-zA-Z0-9 .,%()/-]{1,64}$/;

/** The Graphite tokens the frame gets as CSS variables (frame shim). */
export const THEME_TOKENS = [
  "--background",
  "--foreground",
  "--card",
  "--card-foreground",
  "--primary",
  "--primary-foreground",
  "--muted",
  "--muted-foreground",
  "--accent",
  "--accent-foreground",
  "--destructive",
  "--border",
  "--ring",
] as const;

export interface FrameLike {
  readonly contentWindow: Pick<Window, "postMessage"> | null;
}

export interface FrameRefusal {
  reason: string;
  type?: string;
}

export interface ArtifactFrameOptions {
  theme: FrameTheme;
  vars?: Record<string, string>;
  onReady?(): void;
  onSize?(height: number): void;
  /** An https link the frame asked to open: the host asks the owner first. */
  onOpenRequest?(url: string): void;
  onTornDown(reason: string): void;
  reportRefusal(refusal: FrameRefusal): void;
  nonce?: string;
  createChannel?: () => MessageChannel;
  helloGraceMs?: number;
  settleMs?: number;
  now?: () => number;
}

/** 128 random bits, base64url. */
export function newFrameNonce(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  let text = "";
  for (const b of bytes) text += String.fromCharCode(b);
  return btoa(text).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/** The iframe src: the gateway's frame URL plus the per-view fragment. */
export function frameSrc(url: string, nonce: string, theme: FrameTheme) {
  return `${url}#n=${nonce}&t=${theme}`;
}

/** Only well-formed custom properties with plain values. */
export function cleanVars(
  vars: Record<string, string> | undefined,
): Record<string, string> {
  const out: Record<string, string> = {};
  let count = 0;
  for (const [k, v] of Object.entries(vars ?? {})) {
    if (++count > 64) break;
    if (VAR_NAME.test(k) && typeof v === "string" && VAR_VALUE.test(v.trim()))
      out[k] = v.trim();
  }
  return out;
}

/** The Graphite tokens: with no theme, the page's current ones, read from
 * <html>; with a theme, that theme's, read from a hidden element carrying
 * its class (globals.css defines both `.light` and `.dark` on any element),
 * so the app's own theme is not touched. */
export function readThemeVars(theme?: FrameTheme): Record<string, string> {
  if (typeof window === "undefined") return {};
  let probe: HTMLElement | null = null;
  if (theme) {
    probe = document.createElement("div");
    probe.className = theme;
    probe.setAttribute("aria-hidden", "true");
    probe.style.display = "none";
    document.body.appendChild(probe);
  }
  try {
    const style = getComputedStyle(probe ?? document.documentElement);
    const out: Record<string, string> = {};
    for (const name of THEME_TOKENS) {
      const value = style.getPropertyValue(name).trim();
      if (value) out[name] = value;
    }
    return cleanVars(out);
  } finally {
    probe?.remove();
  }
}

export type FrameMessage =
  | { v: 1; type: "ready" }
  | { v: 1; type: "size"; height: number }
  | { v: 1; type: "open"; url: string };

function plain(value: unknown): value is Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value))
    return false;
  const proto = Object.getPrototypeOf(value) as unknown;
  return proto === Object.prototype || proto === null;
}

function exactKeys(obj: Record<string, unknown>, keys: string[]): boolean {
  const own = Object.keys(obj);
  return own.length === keys.length && keys.every((k) => own.includes(k));
}

/** A frame → host message, or the reason it is refused. */
export function checkFrameMessage(
  data: unknown,
):
  | { ok: true; message: FrameMessage }
  | { ok: false; reason: string; type?: string } {
  if (!plain(data)) return { ok: false, reason: "not_an_object" };
  const type =
    typeof data.type === "string" && /^[a-z][a-z0-9_]{0,31}$/.test(data.type)
      ? data.type
      : undefined;
  if (data.v !== 1) return { ok: false, reason: "bad_version", type };
  switch (data.type) {
    case "ready":
      return exactKeys(data, ["v", "type"])
        ? { ok: true, message: { v: 1, type: "ready" } }
        : { ok: false, reason: "bad_shape", type };
    case "size": {
      if (
        !exactKeys(data, ["v", "type", "height"]) ||
        typeof data.height !== "number" ||
        !Number.isFinite(data.height)
      )
        return { ok: false, reason: "bad_shape", type };
      const height = Math.round(
        Math.min(SIZE_MAX, Math.max(SIZE_MIN, data.height)),
      );
      return { ok: true, message: { v: 1, type: "size", height } };
    }
    case "open": {
      if (
        !exactKeys(data, ["v", "type", "url"]) ||
        typeof data.url !== "string" ||
        data.url.length > 2048
      )
        return { ok: false, reason: "bad_shape", type };
      const url = checkOpenUrl(data.url);
      return url
        ? { ok: true, message: { v: 1, type: "open", url } }
        : { ok: false, reason: "link_refused", type };
    }
    default:
      return { ok: false, reason: "unknown_type", type };
  }
}

/** https only, no credentials; the normalised URL or null. */
export function checkOpenUrl(raw: string): string | null {
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    return null;
  }
  if (
    url.protocol !== "https:" ||
    url.username ||
    url.password ||
    !url.hostname
  )
    return null;
  return url.toString();
}

function helloNonce(data: unknown): string | null {
  if (
    !plain(data) ||
    data.v !== 1 ||
    data.type !== "hello" ||
    !exactKeys(data, ["v", "type", "nonce"])
  )
    return null;
  return typeof data.nonce === "string" ? data.nonce : null;
}

type Phase = "waiting" | "connected" | "torn-down" | "disposed";

export class ArtifactFrameController {
  readonly nonce: string;
  private phase: Phase = "waiting";
  private loads = 0;
  private hellos = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private port: MessagePort | null = null;
  private frame: FrameLike | null = null;
  private theme: FrameTheme;
  private vars: Record<string, string>;
  private stamps: number[] = [];
  private reports = 0;
  private readonly now: () => number;
  /** Host → frame messages actually posted (tests read it). */
  readonly sent: unknown[] = [];

  constructor(private readonly opts: ArtifactFrameOptions) {
    this.nonce = opts.nonce ?? newFrameNonce();
    this.theme = opts.theme;
    this.vars = cleanVars(opts.vars);
    this.now = opts.now ?? (() => Date.now());
  }

  get state(): Phase {
    return this.phase;
  }

  attach(frame: FrameLike): void {
    this.frame = frame;
  }

  handleLoad(): void {
    if (this.phase === "disposed" || this.phase === "torn-down") return;
    this.loads += 1;
    if (this.loads > 1) return this.tearDown("second_load");
    this.progress();
  }

  handleWindowMessage(event: Pick<MessageEvent, "source" | "data">): void {
    if (this.phase === "disposed" || this.phase === "torn-down") return;
    const win = this.frame?.contentWindow;
    if (!win || event.source !== (win as unknown)) return; // another window
    const nonce = helloNonce(event.data);
    if (nonce === null) {
      this.report({ reason: "not_on_port" });
      return;
    }
    if (nonce !== this.nonce) return this.tearDown("bad_nonce");
    this.hellos += 1;
    if (this.hellos > 1 || this.phase !== "waiting")
      return this.tearDown("second_document");
    this.progress();
  }

  setTheme(theme: FrameTheme, vars?: Record<string, string>): void {
    this.theme = theme;
    if (vars) this.vars = cleanVars(vars);
    this.post({ v: 1, type: "theme", theme: this.theme, vars: this.vars });
  }

  dispose(): void {
    this.clearTimer();
    this.closePort();
    this.phase = "disposed";
  }

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
    }, this.opts.helloGraceMs ?? 3000);
  }

  private handshake(): void {
    const target = this.frame?.contentWindow;
    if (!target) return;
    const channel = this.opts.createChannel?.() ?? new MessageChannel();
    this.port = channel.port1;
    this.port.onmessage = (e) => this.handlePortMessage(e);
    this.phase = "connected";
    const init = { v: 1, type: "init", theme: this.theme, vars: this.vars };
    this.sent.push(init);
    target.postMessage(init, "*", [channel.port2]);
  }

  private handlePortMessage(event: MessageEvent): void {
    if (this.phase !== "connected") return;
    const t = this.now();
    this.stamps = this.stamps.filter((s) => t - s < 1000);
    if (this.stamps.length >= MAX_MESSAGES_PER_SECOND) {
      for (const p of event.ports ?? []) p.close();
      this.report({ reason: "rate_limited" });
      return;
    }
    this.stamps.push(t);
    if (event.ports && event.ports.length > 0) {
      for (const p of event.ports) p.close();
      this.report({ reason: "transfer_refused" });
      return;
    }
    const check = checkFrameMessage(event.data);
    if (!check.ok) {
      this.report({ reason: check.reason, type: check.type });
      return;
    }
    const m = check.message;
    if (m.type === "ready") this.opts.onReady?.();
    else if (m.type === "size") this.opts.onSize?.(m.height);
    else this.opts.onOpenRequest?.(m.url);
  }

  private post(message: unknown): void {
    if (this.phase !== "connected" || !this.port) return;
    this.sent.push(message);
    this.port.postMessage(message);
  }

  private report(refusal: FrameRefusal): void {
    if (this.reports >= 20) return;
    this.reports += 1;
    this.opts.reportRefusal(refusal);
  }

  private tearDown(reason: string): void {
    this.clearTimer();
    this.closePort();
    this.phase = "torn-down";
    this.report({ reason });
    this.opts.onTornDown(reason);
  }

  private clearTimer(): void {
    if (this.timer !== null) clearTimeout(this.timer);
    this.timer = null;
  }

  private closePort(): void {
    if (this.port) {
      this.port.onmessage = null;
      this.port.close();
      this.port = null;
    }
  }
}
