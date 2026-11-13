import { afterEach, describe, expect, it, vi } from "vitest";

import {
  AppHostController,
  type HostControllerOptions,
  type Refusal,
} from "@/core/apps/host-controller";
import type { SourceResult } from "@/core/apps/protocol";

/**
 * Spec 011 FR-020..FR-022: the host side of one frame. A real MessageChannel
 * (Node has one); the frame is a stand-in whose contentWindow records what
 * the host posts to it, and the test plays the shim on port 2.
 */

const FRESH: SourceResult = {
  source: "calendar",
  state: "fresh",
  data: { items: [{ title: "Standup" }] },
  fetched_at: "2026-11-13T10:00:00+00:00",
  stale: false,
  reason: null,
};

interface Harness {
  controller: AppHostController;
  frameWindow: { postMessage: ReturnType<typeof vi.fn> };
  port: () => MessagePort;
  received: unknown[];
  refusals: Refusal[];
  fetches: { source: string; refresh: boolean }[];
  opened: string[];
  internal: string[];
  connects: string[];
  torn: { count: number };
  next: () => Promise<unknown>;
}

const open: MessagePort[] = [];
afterEach(() => {
  for (const p of open.splice(0)) p.close();
});

function harness(over: Partial<HostControllerOptions> = {}): Harness {
  const received: unknown[] = [];
  const waiters: ((m: unknown) => void)[] = [];
  const refusals: Refusal[] = [];
  const fetches: { source: string; refresh: boolean }[] = [];
  const opened: string[] = [];
  const internal: string[] = [];
  const connects: string[] = [];
  const torn = { count: 0 };
  let port2: MessagePort | null = null;
  const frameWindow = {
    postMessage: vi.fn((_m: unknown, _o: string, transfer: MessagePort[]) => {
      port2 = transfer[0]!;
      open.push(port2);
      port2.onmessage = (e) => {
        received.push(e.data);
        waiters.shift()?.(e.data);
      };
    }),
  };
  const controller = new AppHostController({
    appId: "today",
    version: 3,
    approvedSources: ["calendar", "inbox"],
    linkHosts: ["github.com"],
    origin: "https://omni.example",
    theme: "light",
    prefetch: null,
    fetchSource: async (source, refresh) => {
      fetches.push({ source, refresh });
      return { ...FRESH, source };
    },
    reportRefusal: (r) => refusals.push(r),
    openExternal: (u) => opened.push(u),
    openInternal: (p) => internal.push(p),
    onConnect: (s) => connects.push(s),
    onTornDown: () => {
      torn.count += 1;
    },
    ...over,
  });
  controller.attach({ contentWindow: frameWindow as unknown as Window });
  return {
    controller,
    frameWindow,
    port: () => port2!,
    received,
    refusals,
    fetches,
    opened,
    internal,
    connects,
    torn,
    next: () => new Promise((resolve) => waiters.push(resolve)),
  };
}

const settle = () => new Promise((r) => setTimeout(r, 20));

describe("the handshake", () => {
  it("posts init with one port to the frame's own window on the first load", () => {
    const h = harness();
    h.controller.handleLoad();
    expect(h.frameWindow.postMessage).toHaveBeenCalledTimes(1);
    const [msg, origin, transfer] = h.frameWindow.postMessage.mock.calls[0]!;
    expect(msg).toEqual({
      v: 1,
      type: "init",
      app: "today",
      version: 3,
      theme: "light",
    });
    expect(origin).toBe("*");
    expect(transfer).toHaveLength(1);
    expect(h.controller.state).toBe("connected");
  });

  it("a second load closes the port and tears the frame down: no second handshake", async () => {
    const h = harness();
    h.controller.handleLoad();
    h.controller.handleLoad();
    expect(h.frameWindow.postMessage).toHaveBeenCalledTimes(1);
    expect(h.torn.count).toBe(1);
    expect(h.controller.state).toBe("torn-down");
    // The old port is dead: a request on it gets nothing back.
    h.port().postMessage({ v: 1, type: "data", id: "r1", source: "calendar" });
    await settle();
    expect(h.received).toEqual([]);
    expect(h.fetches).toEqual([]);
    // And a third load does nothing either.
    h.controller.handleLoad();
    expect(h.frameWindow.postMessage).toHaveBeenCalledTimes(1);
  });
});

describe("messages on the port", () => {
  it("answers data from the batch prefetch, refresh from the bridge", async () => {
    const h = harness({
      prefetch: Promise.resolve({ calendar: FRESH }),
    });
    h.controller.handleLoad();
    h.port().postMessage({ v: 1, type: "data", id: "r1", source: "calendar" });
    expect(await h.next()).toMatchObject({
      type: "result",
      id: "r1",
      state: "fresh",
    });
    expect(h.fetches).toEqual([]);
    h.port().postMessage({
      v: 1,
      type: "refresh",
      id: "r2",
      source: "calendar",
    });
    expect(await h.next()).toMatchObject({ type: "result", id: "r2" });
    expect(h.fetches).toEqual([{ source: "calendar", refresh: true }]);
  });

  it("refuses an unapproved source before any request, answers and reports it", async () => {
    const h = harness();
    h.controller.handleLoad();
    h.port().postMessage({
      v: 1,
      type: "data",
      id: "r1",
      source: "inbox_bodies",
    });
    expect(await h.next()).toEqual({
      v: 1,
      type: "error",
      id: "r1",
      reason: "source_not_approved",
    });
    expect(h.fetches).toEqual([]);
    expect(h.refusals).toEqual([
      { reason: "source_not_approved", type: "data", source: "inbox_bodies" },
    ]);
  });

  it("refuses malformed and oversized messages the same way", async () => {
    const h = harness();
    h.controller.handleLoad();
    h.port().postMessage({
      v: 1,
      type: "refresh",
      id: "r1",
      source: "calendar",
      params: {},
    });
    expect(await h.next()).toMatchObject({
      type: "error",
      reason: "unknown_key:params",
    });
    h.port().postMessage({
      v: 1,
      type: "open",
      url: "https://github.com/" + "a".repeat(9000),
    });
    expect(await h.next()).toMatchObject({ type: "error" });
    h.port().postMessage("data calendar");
    expect(await h.next()).toMatchObject({
      type: "error",
      reason: "not_an_object",
    });
    expect(h.fetches).toEqual([]);
    expect(h.refusals.map((r) => r.reason)).toEqual([
      "unknown_key:params",
      "too_large",
      "not_an_object",
    ]);
  });

  it("a flood: 30 a second are served, the rest refused, and reported once", async () => {
    let t = 0;
    const h = harness({ now: () => t });
    h.controller.handleLoad();
    for (let i = 0; i < 100; i++) {
      h.port().postMessage({
        v: 1,
        type: "data",
        id: `r${i}`,
        source: "calendar",
      });
    }
    await settle();
    expect(h.fetches).toHaveLength(30);
    const errors = h.received.filter(
      (m) => (m as { type: string }).type === "error",
    );
    expect(errors).toEqual([
      { v: 1, type: "error", id: null, reason: "rate_limited" },
    ]);
    expect(h.refusals.filter((r) => r.reason === "rate_limited")).toHaveLength(
      1,
    );
    t = 1500;
    h.port().postMessage({
      v: 1,
      type: "data",
      id: "late",
      source: "calendar",
    });
    await settle();
    expect(h.fetches).toHaveLength(31);
  });

  it("open: an allowed link is opened by the host; anything else is refused", async () => {
    const h = harness();
    h.controller.handleLoad();
    h.port().postMessage({
      v: 1,
      type: "open",
      url: "https://github.com/a/b/pull/1",
    });
    h.port().postMessage({ v: 1, type: "open", url: "/workspace/projects/p1" });
    h.port().postMessage({
      v: 1,
      type: "open",
      url: "https://evil.example/steal",
    });
    await settle();
    expect(h.opened).toEqual(["https://github.com/a/b/pull/1"]);
    expect(h.internal).toEqual(["/workspace/projects/p1"]);
    expect(h.received).toEqual([
      { v: 1, type: "error", id: null, reason: "url_not_allowed" },
    ]);
    expect(h.refusals).toEqual([{ reason: "url_not_allowed", type: "open" }]);
  });

  it("connect opens the host's own sheet, for an approved source only", async () => {
    const h = harness();
    h.controller.handleLoad();
    h.port().postMessage({ v: 1, type: "connect", source: "calendar" });
    h.port().postMessage({ v: 1, type: "connect", source: "github" });
    await settle();
    expect(h.connects).toEqual(["calendar"]);
    expect(h.refusals).toMatchObject([{ reason: "source_not_approved" }]);
  });

  it("a port sent along with a message is closed and refused", async () => {
    const h = harness();
    h.controller.handleLoad();
    const extra = new MessageChannel();
    open.push(extra.port1, extra.port2);
    h.port().postMessage({ v: 1, type: "data", id: "r1", source: "calendar" }, [
      extra.port2,
    ]);
    expect(await h.next()).toMatchObject({
      type: "error",
      reason: "transfer_refused",
    });
    expect(h.fetches).toEqual([]);
  });
});

describe("window messages", () => {
  it("are never acted on; protocol-looking ones are refused and reported", async () => {
    const h = harness();
    h.controller.handleLoad();
    const other = {};
    // From the app frame, but not on the port.
    h.controller.handleWindowMessage({
      source: h.frameWindow as unknown as Window,
      data: { v: 1, type: "data", id: "r1", source: "calendar" },
    });
    // From some other window.
    h.controller.handleWindowMessage({
      source: other as Window,
      data: { v: 1, type: "data", id: "r2", source: "calendar" },
    });
    // The shim's ready, from the frame: accepted silently.
    h.controller.handleWindowMessage({
      source: h.frameWindow as unknown as Window,
      data: { v: 1, type: "ready" },
    });
    // Someone else's message (not the protocol): ignored, not reported.
    h.controller.handleWindowMessage({
      source: other as Window,
      data: "hello",
    });
    await settle();
    expect(h.fetches).toEqual([]);
    expect(h.refusals).toEqual([
      { reason: "not_on_port", type: "data", source: "calendar" },
      { reason: "wrong_window", type: "data", source: "calendar" },
    ]);
  });
});

describe("theme and updates", () => {
  it("passes a theme change in, live, and pushes updates for approved sources only", async () => {
    const h = harness();
    h.controller.handleLoad();
    h.controller.setTheme("dark");
    h.controller.setTheme("dark");
    h.controller.pushUpdate("inbox", { ...FRESH, source: "inbox" });
    h.controller.pushUpdate("secrets", { ...FRESH, source: "secrets" });
    await settle();
    expect(h.received).toEqual([
      { v: 1, type: "theme", theme: "dark" },
      expect.objectContaining({
        type: "update",
        source: "inbox",
        state: "fresh",
      }),
    ]);
  });
});
