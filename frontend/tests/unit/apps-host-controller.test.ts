import { afterEach, describe, expect, it, vi } from "vitest";

import {
  AppHostController,
  reportOf,
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
  /** The shim's hello (from the frame, with the nonce) and the load. */
  hello: (nonce?: string) => void;
  open: () => Promise<void>;
}

const NONCE = "n0nce-n0nce-n0nce-0123";

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
    nonce: NONCE,
    settleMs: 0,
    helloGraceMs: 30,
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
    hello: (nonce = NONCE) =>
      controller.handleWindowMessage({
        source: frameWindow as unknown as Window,
        data: { v: 1, type: "hello", nonce },
      }),
    open: async () => {
      controller.handleWindowMessage({
        source: frameWindow as unknown as Window,
        data: { v: 1, type: "hello", nonce: NONCE },
      });
      controller.handleLoad();
      await new Promise((r) => setTimeout(r, 5));
    },
  };
}

const settle = () => new Promise((r) => setTimeout(r, 20));

describe("the handshake", () => {
  it("posts init with one port, only after one hello with the nonce and one load", async () => {
    const h = harness();
    h.controller.handleLoad();
    await settle();
    expect(h.frameWindow.postMessage).not.toHaveBeenCalled();
    h.hello();
    await settle();
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
    await h.open();
    h.controller.handleLoad();
    expect(h.frameWindow.postMessage).toHaveBeenCalledTimes(1);
    expect(h.torn.count).toBe(1);
    expect(h.controller.state).toBe("torn-down");
    expect(h.refusals).toEqual([{ reason: "second_load" }]);
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
    await h.open();
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
    await h.open();
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
    await h.open();
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
    // The frame is told the detail; the audit gets codes only (api.md).
    expect(h.refusals).toEqual([
      { reason: "invalid_message", type: "refresh", source: "calendar" },
      { reason: "oversized", type: "open" },
      { reason: "invalid_message" },
    ]);
  });

  it("a flood: 30 a second are served, the rest refused, and reported once", async () => {
    let t = 0;
    const h = harness({ now: () => t });
    await h.open();
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
    await h.open();
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
    await h.open();
    h.port().postMessage({ v: 1, type: "connect", source: "calendar" });
    h.port().postMessage({ v: 1, type: "connect", source: "github" });
    await settle();
    expect(h.connects).toEqual(["calendar"]);
    expect(h.refusals).toMatchObject([{ reason: "source_not_approved" }]);
  });

  it("a port sent along with a message is closed and refused", async () => {
    const h = harness();
    await h.open();
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
  it("are never acted on; the frame's are reported, other windows' dropped quietly", async () => {
    const h = harness();
    await h.open();
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
    // Someone else's message (not the protocol): ignored, not reported.
    h.controller.handleWindowMessage({
      source: other as Window,
      data: "hello",
    });
    await settle();
    expect(h.fetches).toEqual([]);
    expect(h.refusals).toEqual([
      { reason: "not_on_port", type: "data", source: "calendar" },
    ]);
  });
});

describe("theme and updates", () => {
  it("passes a theme change in, live, and pushes updates for approved sources only", async () => {
    const h = harness();
    await h.open();
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

describe("refusal reports", () => {
  it("carry codes only: no free text from the frame reaches the audit", () => {
    expect(
      reportOf({
        reason: "unknown_key:<script>",
        type: "data",
        source: "calendar",
      }),
    ).toEqual({
      reason: "invalid_message",
      type: "data",
      source: "calendar",
    });
    expect(reportOf({ reason: "too_large" })).toEqual({ reason: "oversized" });
    expect(
      reportOf({
        reason: "source_not_approved",
        type: "data",
        source: "inbox_bodies",
      }),
    ).toEqual({
      reason: "source_not_approved",
      type: "data",
      source: "inbox_bodies",
    });
    // A type or source that is not a valid name is left out, not cleaned up.
    expect(
      reportOf({
        reason: "unknown_type",
        type: "Hello World",
        source: "../../etc",
      }),
    ).toEqual({
      reason: "unknown_type",
    });
    for (const r of [
      "rate_limited",
      "url_not_allowed",
      "not_on_port",
      "second_document",
      "no_hello",
      "bad_nonce",
      "transfer_refused",
      "second_load",
    ]) {
      expect(reportOf({ reason: r }).reason).toMatch(/^[a-z][a-z0-9_]{0,47}$/);
    }
  });
});

describe("the handshake is bound to one app document (M1)", () => {
  it("a second hello (a replacement document) before the load: no port, torn down", async () => {
    const h = harness();
    h.hello();
    h.hello();
    h.controller.handleLoad();
    await settle();
    expect(h.frameWindow.postMessage).not.toHaveBeenCalled();
    expect(h.torn.count).toBe(1);
    expect(h.refusals).toEqual([{ reason: "second_document" }]);
  });

  it("a second hello inside the settle after the load cancels the handshake", async () => {
    const h = harness({ settleMs: 15 });
    h.hello();
    h.controller.handleLoad();
    h.hello();
    await settle();
    expect(h.frameWindow.postMessage).not.toHaveBeenCalled();
    expect(h.refusals).toEqual([{ reason: "second_document" }]);
  });

  it("a hello after the handshake closes the port", async () => {
    const h = harness();
    await h.open();
    h.hello();
    expect(h.controller.state).toBe("torn-down");
    expect(h.refusals).toEqual([{ reason: "second_document" }]);
  });

  it("a load with no hello (a document without the shim): torn down after the grace", async () => {
    const h = harness();
    h.controller.handleLoad();
    await settle();
    await settle();
    expect(h.frameWindow.postMessage).not.toHaveBeenCalled();
    expect(h.refusals).toEqual([{ reason: "no_hello" }]);
  });

  it("a hello with the wrong nonce, or from another window, never opens it", async () => {
    const h = harness();
    h.controller.handleWindowMessage({
      source: {} as Window,
      data: { v: 1, type: "hello", nonce: NONCE },
    });
    h.controller.handleLoad();
    await settle();
    await settle();
    expect(h.frameWindow.postMessage).not.toHaveBeenCalled();
    const g = harness();
    g.hello("wrong-nonce-wrong-nonce-0");
    expect(g.controller.state).toBe("torn-down");
    expect(g.refusals).toEqual([{ reason: "bad_nonce" }]);
  });

  it("the hello may come after the load, within the grace", async () => {
    const h = harness({ helloGraceMs: 200 });
    h.controller.handleLoad();
    h.hello();
    await settle();
    expect(h.controller.state).toBe("connected");
  });
});

describe("the low-severity guards", () => {
  it("connect: one sheet at a time, then a cooldown after it closes (L3)", async () => {
    let t = 0;
    const h = harness({ now: () => t, connectCooldownMs: 30_000 });
    await h.open();
    h.port().postMessage({ v: 1, type: "connect", source: "calendar" });
    h.port().postMessage({ v: 1, type: "connect", source: "inbox" });
    await settle();
    expect(h.connects).toEqual(["calendar"]);
    h.controller.connectClosed();
    t = 10_000;
    h.port().postMessage({ v: 1, type: "connect", source: "inbox" });
    await settle();
    expect(h.connects).toEqual(["calendar"]);
    t = 31_000;
    h.port().postMessage({ v: 1, type: "connect", source: "inbox" });
    await settle();
    expect(h.connects).toEqual(["calendar", "inbox"]);
    expect(
      h.received.filter(
        (m) => (m as { reason?: string }).reason === "connect_busy",
      ),
    ).toHaveLength(2);
  });

  it("a bridge failure reaches the frame as a fixed sentence, not the error (L4)", async () => {
    const h = harness({
      fetchSource: () =>
        Promise.reject(new Error("secret internal detail at 10.0.0.5")),
    });
    await h.open();
    h.port().postMessage({
      v: 1,
      type: "refresh",
      id: "r1",
      source: "calendar",
    });
    const m = (await h.next()) as { state: string; reason: string };
    expect(m.state).toBe("failed");
    expect(m.reason).toBe("OmniHarness could not read this source just now.");
  });

  it("ports sent with rate-limited messages are closed too (L5)", async () => {
    const t = 0;
    const h = harness({ now: () => t });
    await h.open();
    for (let i = 0; i < 30; i++) {
      h.port().postMessage({
        v: 1,
        type: "data",
        id: `r${i}`,
        source: "calendar",
      });
    }
    const extra = new MessageChannel();
    open.push(extra.port1);
    let closed = false;
    // Node: closing one end of a channel emits "close" on the other.
    (extra.port1 as unknown as { on(e: string, f: () => void): void }).on(
      "close",
      () => {
        closed = true;
      },
    );
    h.port().postMessage({ v: 1, type: "data", id: "x", source: "calendar" }, [
      extra.port2,
    ]);
    await settle();
    await settle();
    expect(closed).toBe(true);
  });
});
