import {
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
  copyFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { runInThisContext } from "node:vm";

import ts from "typescript";
import { afterEach, describe, expect, it, vi } from "vitest";

import { buildShim } from "../../scripts/build-app-shim.mjs";

/**
 * Spec 011 FR-018, FR-023: the platform shim every app carries.
 *
 * - omni-shim.js is exactly what the build makes from its source, the
 *   protocol schema and validate.js (the host's own validator): no drift.
 * - Run against a stand-in window: it takes `init` once, only from
 *   window.parent, only with one port; it validates every host message; it
 *   ignores forged ones; it removes WebRTC; it never evaluates anything.
 * - omni.d.ts compiles, and types `omni.data("name")` from OmniSources.
 */

const SHIM_PATH = new URL(
  "../../src/core/apps/shim/omni-shim.js",
  import.meta.url,
);
const SHIM = readFileSync(SHIM_PATH, "utf8");

describe("the shim file", () => {
  it("is the build of its source, the schema and the host's validator", () => {
    expect(SHIM).toBe(buildShim());
  });

  it("carries the host's validator and schema verbatim", () => {
    const validate = readFileSync(
      new URL("../../src/core/apps/validate.js", import.meta.url),
      "utf8",
    );
    const body = validate.slice(
      validate.indexOf("function validateProtocolMessage"),
    );
    expect(SHIM).toContain(body.trim());
    expect(SHIM).toContain('"frame_to_host_max_bytes":8192');
  });

  it("names none of what registration refuses (it is inlined into every app)", () => {
    // The shim may only mention RTC names inside its removal list.
    const withoutList = SHIM.replace(/var RTC = \[[\s\S]*?\];/, "");
    for (const banned of [
      "RTCPeerConnection",
      "RTCDataChannel",
      "WebSocket",
      "eval(",
      "new Function",
    ]) {
      expect(withoutList, banned).not.toContain(banned);
    }
  });
});

type Listener = (event: unknown) => void;

interface FakePort {
  postMessage: ReturnType<typeof vi.fn>;
  onmessage: ((event: { data: unknown; ports?: unknown[] }) => void) | null;
}

interface Env {
  win: Record<string, unknown> & { omni: OmniLike };
  parent: { postMessage: ReturnType<typeof vi.fn> };
  dispatch: (event: {
    source: unknown;
    data: unknown;
    ports?: unknown[];
  }) => void;
  classes: Set<string>;
  body: { textContent: string };
}

interface OmniLike {
  ready: Promise<unknown>;
  data(name: string): Promise<unknown>;
  refresh(name: string): Promise<unknown>;
  open(url: string): boolean;
  connect(name: string): boolean;
  onTheme(fn: (t: string) => void): () => void;
  onUpdate(fn: (n: string, r: unknown) => void): () => void;
  onError(fn: (r: string) => void): () => void;
  theme: string | null;
  describe(r: unknown): { label: string; detail: string };
}

const saved: Record<string, unknown> = {};
afterEach(() => {
  for (const k of ["window", "document"]) {
    if (saved[k] === undefined)
      delete (globalThis as Record<string, unknown>)[k];
    else (globalThis as Record<string, unknown>)[k] = saved[k];
  }
});

const NONCE = "n0nce-n0nce-n0nce-0123";

/** Stand-ins for the DOM prototypes the shim guards (fresh per load). */
let FakeDocument: { prototype: Record<string, unknown> };
let FakeElement: { prototype: Record<string, unknown> };
function freshDom() {
  class D {
    createElement(name: string) {
      return { localName: String(name).toLowerCase() };
    }
    createElementNS(_ns: string, q: string) {
      return { localName: q };
    }
    write(_html: string) {
      return undefined;
    }
  }
  class E {
    html = "";
    get innerHTML() {
      return this.html;
    }
    set innerHTML(v: string) {
      this.html = v;
    }
    insertAdjacentHTML(_where: string, v: string) {
      this.html += v;
    }
  }
  FakeDocument = D as unknown as typeof FakeDocument;
  FakeElement = E as unknown as typeof FakeElement;
}

function load({ topLevel = false } = {}): Env {
  freshDom();
  const listeners: Record<string, Listener[]> = {};
  const parent = { postMessage: vi.fn() };
  const classes = new Set<string>();
  const body = { textContent: "app" };
  const win: Record<string, unknown> = {
    addEventListener: (t: string, fn: Listener) =>
      (listeners[t] ??= []).push(fn),
    removeEventListener: (t: string, fn: Listener) => {
      listeners[t] = (listeners[t] ?? []).filter((f) => f !== fn);
    },
    RTCPeerConnection: class RTCPeerConnection {},
    RTCDataChannel: class RTCDataChannel {},
    webkitRTCPeerConnection: class webkitRTCPeerConnection {},
    XSLTProcessor: class XSLTProcessor {},
    location: { hash: `#omni-nonce=${NONCE}` },
    Document: FakeDocument,
    Element: FakeElement,
  };
  win.parent = topLevel ? win : parent;
  const doc = {
    readyState: "complete",
    body,
    documentElement: {
      classList: {
        add: (c: string) => classes.add(c),
        remove: (c: string) => classes.delete(c),
      },
      style: {} as Record<string, string>,
    },
    addEventListener: () => undefined,
  };
  saved.window = (globalThis as Record<string, unknown>).window;
  saved.document = (globalThis as Record<string, unknown>).document;
  (globalThis as Record<string, unknown>).window = win;
  (globalThis as Record<string, unknown>).document = doc;
  runInThisContext(SHIM);
  return {
    win: win as Env["win"],
    parent,
    dispatch: (event) => {
      for (const fn of [...(listeners.message ?? [])])
        fn({ ports: [], ...event });
    },
    classes,
    body,
  };
}

const port = (): FakePort => ({ postMessage: vi.fn(), onmessage: null });
const INIT = { v: 1, type: "init", app: "today", version: 3, theme: "dark" };
const flush = () => new Promise((r) => setTimeout(r, 0));

describe("the shim at run time", () => {
  it("removes the WebRTC constructors for good", () => {
    const env = load();
    expect(env.win.RTCPeerConnection).toBeUndefined();
    expect(env.win.RTCDataChannel).toBeUndefined();
    expect(env.win.webkitRTCPeerConnection).toBeUndefined();
    expect(() => {
      "use strict";
      env.win.RTCPeerConnection = class Again {};
    }).toThrow();
    expect(env.win.RTCPeerConnection).toBeUndefined();
  });

  it("says hello with its nonce to its parent, and exposes a frozen omni", () => {
    const env = load();
    expect(env.parent.postMessage).toHaveBeenCalledWith(
      { v: 1, type: "hello", nonce: NONCE },
      "*",
    );
    expect(env.parent.postMessage).toHaveBeenCalledTimes(1);
    expect(Object.isFrozen(env.win.omni)).toBe(true);
    expect(() => {
      (env.win as Record<string, unknown>).omni = {};
    }).toThrow();
  });

  it("takes init once, from window.parent, with exactly one port", async () => {
    const env = load();
    const p = port();
    // From another window: ignored.
    env.dispatch({ source: {}, data: INIT, ports: [port()] });
    // From the parent but with no port, or two: ignored.
    env.dispatch({ source: env.parent, data: INIT, ports: [] });
    env.dispatch({ source: env.parent, data: INIT, ports: [port(), port()] });
    // Malformed init from the parent: ignored.
    env.dispatch({
      source: env.parent,
      data: { ...INIT, token: "x" },
      ports: [port()],
    });
    expect(env.win.omni.theme).toBeNull();
    // The real one.
    env.dispatch({ source: env.parent, data: INIT, ports: [p] });
    await expect(env.win.omni.ready).resolves.toEqual({
      app: "today",
      version: 3,
      theme: "dark",
    });
    expect(env.classes.has("dark")).toBe(true);
    // A forged second init, even from the parent with a port: ignored.
    const forged = port();
    env.dispatch({
      source: env.parent,
      data: { ...INIT, app: "evil", theme: "light" },
      ports: [forged],
    });
    expect(env.win.omni.theme).toBe("dark");
    void env.win.omni.data("calendar");
    await flush();
    expect(forged.postMessage).not.toHaveBeenCalled();
    expect(p.postMessage).toHaveBeenCalledWith({
      v: 1,
      type: "data",
      id: "r1",
      source: "calendar",
    });
  });

  it("accepts results only on its port, matching an open request", async () => {
    const env = load();
    const p = port();
    env.dispatch({ source: env.parent, data: INIT, ports: [p] });
    const pending = env.win.omni.data("calendar");
    await flush();
    // A forged result on the window (not the port): ignored.
    env.dispatch({
      source: env.parent,
      data: {
        v: 1,
        type: "result",
        id: "r1",
        source: "calendar",
        state: "fresh",
        data: { forged: true },
        fetched_at: null,
        stale: false,
      },
    });
    // On the port, but for another source, or malformed: ignored.
    p.onmessage!({
      data: {
        v: 1,
        type: "result",
        id: "r1",
        source: "inbox",
        state: "fresh",
        data: {},
        fetched_at: null,
        stale: false,
      },
    });
    p.onmessage!({
      data: {
        v: 1,
        type: "result",
        id: "r1",
        source: "calendar",
        state: "hacked",
        data: {},
        fetched_at: null,
        stale: false,
      },
    });
    p.onmessage!({
      data: {
        v: 1,
        type: "result",
        id: "r1",
        source: "calendar",
        state: "fresh",
        data: {},
        fetched_at: null,
        stale: false,
        script: "alert(1)",
      },
    });
    // The real one.
    p.onmessage!({
      data: {
        v: 1,
        type: "result",
        id: "r1",
        source: "calendar",
        state: "fresh",
        data: { items: [1] },
        fetched_at: "2026-11-13T10:00:00Z",
        stale: false,
        reason: null,
      },
    });
    await expect(pending).resolves.toEqual({
      source: "calendar",
      state: "fresh",
      data: { items: [1] },
      fetched_at: "2026-11-13T10:00:00Z",
      stale: false,
      reason: null,
    });
  });

  it("rejects a request the host refused, and passes theme and updates on", async () => {
    const env = load();
    const p = port();
    env.dispatch({ source: env.parent, data: INIT, ports: [p] });
    const themes: string[] = [];
    const updates: string[] = [];
    const errors: string[] = [];
    env.win.omni.onTheme((t) => themes.push(t));
    env.win.omni.onUpdate((n) => updates.push(n));
    env.win.omni.onError((r) => errors.push(r));
    const pending = env.win.omni.data("inbox_bodies");
    await flush();
    p.onmessage!({
      data: { v: 1, type: "error", id: "r1", reason: "source_not_approved" },
    });
    await expect(pending).rejects.toThrow("source_not_approved");
    p.onmessage!({ data: { v: 1, type: "theme", theme: "light" } });
    p.onmessage!({ data: { v: 1, type: "theme", theme: "sepia" } });
    p.onmessage!({
      data: {
        v: 1,
        type: "update",
        source: "inbox",
        state: "empty",
        data: { items: [] },
        fetched_at: null,
        stale: false,
      },
    });
    expect(themes).toEqual(["dark", "light"]);
    expect(env.classes.has("dark")).toBe(false);
    expect(updates).toEqual(["inbox"]);
    expect(errors).toEqual(["source_not_approved"]);
  });

  it("validates its own messages before sending", async () => {
    const env = load();
    const p = port();
    env.dispatch({ source: env.parent, data: INIT, ports: [p] });
    await expect(env.win.omni.data("Not A Name")).rejects.toThrow(
      "bad_value:source",
    );
    expect(env.win.omni.open("https://github.com/" + "a".repeat(3000))).toBe(
      false,
    );
    expect(env.win.omni.connect("calendar")).toBe(true);
    expect(p.postMessage).toHaveBeenCalledTimes(1);
  });

  it("opened as a page of its own, it says to open it from OmniHarness", () => {
    const env = load({ topLevel: true });
    expect(env.body.textContent).toBe("Open this app from OmniHarness.");
  });

  it("words each tile state the same way for every app", () => {
    const env = load();
    const d = (r: unknown) => env.win.omni.describe(r);
    expect(d({ state: "empty", fetched_at: null }).label).toBe("Nothing today");
    expect(d({ state: "not_connected" }).label).toBe("Not connected");
    expect(d({ state: "failed", reason: "Gmail did not answer" })).toEqual({
      label: "Can't tell",
      detail: "Gmail did not answer",
    });
    expect(
      d({
        state: "fresh",
        fetched_at: new Date(Date.now() - 4 * 60_000).toISOString(),
      }).label,
    ).toBe("updated 4 min ago");
  });
});

describe("omni.d.ts", () => {
  it("compiles, and types omni.data by the manifest's source names", () => {
    const dir = mkdtempSync(join(tmpdir(), "omni-dts-"));
    try {
      copyFileSync(
        new URL("../../src/core/apps/shim/omni.d.ts", import.meta.url),
        join(dir, "omni.d.ts"),
      );
      writeFileSync(
        join(dir, "app.ts"),
        [
          'import type { CatalogData } from "./omni";',
          'declare module "./omni" {',
          '  interface OmniSources { calendar: CatalogData["googlecalendar.events_today"]; inbox: CatalogData["gmail.unread_subjects"] }',
          "}",
          "export async function main() {",
          '  const r = await omni.data("calendar");',
          "  const titles: (string | undefined)[] = r.data ? r.data.items.map((i) => i.title) : [];",
          '  const n = await window.omni.data("inbox");',
          "  const count: number | undefined = n.data?.count;",
          "  omni.onTheme((t) => t === 'dark');",
          "  return [titles, count, omni.describe(r).label];",
          "}",
          "// @ts-expect-error: not a source of this app",
          'void omni.data("nope");',
        ].join("\n"),
      );
      const program = ts.createProgram([join(dir, "app.ts")], {
        strict: true,
        noEmit: true,
        target: ts.ScriptTarget.ES2022,
        module: ts.ModuleKind.ESNext,
        moduleResolution: ts.ModuleResolutionKind.Bundler,
        lib: ["lib.es2022.d.ts", "lib.dom.d.ts"],
        skipLibCheck: false,
      });
      const diagnostics = ts
        .getPreEmitDiagnostics(program)
        .map((d) => ts.flattenDiagnosticMessageText(d.messageText, "\n"));
      expect(diagnostics).toEqual([]);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  }, // It runs the TypeScript compiler over omni.d.ts and lib.dom: seconds on
  // a CI runner, so not the default 5 s.
  30_000);
});

describe("the shim's second layer against other realms (H1)", () => {
  it("refuses to create any frame element, by DOM call or HTML string", () => {
    const env = load();
    const D = env.win.Document as new () => {
      createElement(n: string): { localName: string };
      createElementNS(ns: string, q: string): unknown;
      write(h: string): void;
    };
    const doc = new D();
    for (const tag of [
      "iframe",
      "IFRAME",
      "frame",
      "object",
      "embed",
      "frameset",
      "portal",
      "fencedframe",
    ]) {
      expect(() => doc.createElement(tag), tag).toThrow(
        "Apps cannot create frames.",
      );
    }
    expect(() =>
      doc.createElementNS("http://www.w3.org/1999/xhtml", "html:iframe"),
    ).toThrow();
    expect(doc.createElement("div").localName).toBe("div");
    expect(() => doc.write('<iframe srcdoc="x">')).toThrow();
    const E = env.win.Element as new () => {
      innerHTML: string;
      insertAdjacentHTML(w: string, h: string): void;
    };
    const el = new E();
    el.innerHTML = "<b>fine</b>";
    expect(el.innerHTML).toBe("<b>fine</b>");
    for (const html of [
      '<iframe srcdoc="x"></iframe>',
      "<IFRAME>",
      "< embed>",
      "<object data=x>",
      "<div><frame></div>",
    ]) {
      expect(() => {
        el.innerHTML = html;
      }, html).toThrow();
      expect(() => el.insertAdjacentHTML("beforeend", html), html).toThrow();
    }
    // Words that merely start alike are fine.
    el.innerHTML = "<p>iframe embed object</p><iframes-list></iframes-list>";
  });

  it("removes XSLT, and the guards cannot be put back", () => {
    const env = load();
    expect(env.win.XSLTProcessor).toBeUndefined();
    const proto = (env.win.Document as { prototype: Record<string, unknown> })
      .prototype;
    const guarded = proto.createElement;
    expect(() => {
      proto.createElement = () => ({});
    }).toThrow();
    expect(proto.createElement).toBe(guarded);
  });

  it("says no hello, and takes no init, while WebRTC is still reachable", async () => {
    // A window where the constructors cannot be removed.
    freshDom();
    const listeners: Listener[] = [];
    const parent = { postMessage: vi.fn() };
    const win: Record<string, unknown> = {
      addEventListener: (_t: string, fn: Listener) => listeners.push(fn),
      removeEventListener: () => undefined,
      location: { hash: `#omni-nonce=${NONCE}` },
      Document: FakeDocument,
      Element: FakeElement,
      parent,
    };
    Object.defineProperty(win, "RTCPeerConnection", {
      value: class Stuck {},
      writable: false,
      configurable: false,
    });
    saved.window = (globalThis as Record<string, unknown>).window;
    saved.document = (globalThis as Record<string, unknown>).document;
    (globalThis as Record<string, unknown>).window = win;
    (globalThis as Record<string, unknown>).document = {
      readyState: "complete",
      body: { textContent: "" },
      documentElement: {
        classList: { add: () => 0, remove: () => 0 },
        style: {},
      },
      addEventListener: () => undefined,
    };
    runInThisContext(SHIM);
    expect(parent.postMessage).not.toHaveBeenCalled();
    const p = port();
    for (const fn of listeners) fn({ source: parent, data: INIT, ports: [p] });
    expect((win.omni as OmniLike).theme).toBeNull();
  });
});
