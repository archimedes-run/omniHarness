import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";

import { expect, test, type Frame, type Page } from "@playwright/test";

import {
  demoApp,
  installFakeBridge,
  type BridgeOptions,
} from "./apps/fake-bridge";
import { hostileScript, selfNavigateScript } from "./apps/hostile-app";

/**
 * Spec 011 Security table, the frame's side (FR-016..FR-024): a hostile app
 * against the real host page, a local LISTENER that records every request it
 * gets, and the fake bridge's log. Assertions are on those logs (what
 * reached a server), never on what the app says it managed.
 *
 * Each guard was observed failing under its sabotage (PR description):
 * the frame CSP without connect-src 'none' (APPS_SABOTAGE_FRAME_CSP), the
 * sandbox attribute widened, the host page's frame-src opened, the host's
 * manifest, open-link, rate and port checks removed, the shim's parent and
 * once-only checks removed, the result builder replaced by a spread.
 */

test.use({ timezoneId: "UTC" });

let server: Server;
let listener = "";
const hits: string[] = [];

test.beforeAll(async () => {
  server = createServer((req, res) => {
    hits.push(`${req.method} ${req.url}`);
    res.writeHead(200, {
      "Content-Type": "text/plain",
      "Access-Control-Allow-Origin": "*",
    });
    res.end("ok");
  });
  server.on("upgrade", (req, socket) => {
    hits.push(`UPGRADE ${req.url}`);
    socket.destroy();
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  listener = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
});

test.afterAll(async () => {
  await new Promise((resolve) => server.close(resolve));
});

test.beforeEach(() => {
  hits.length = 0;
});

const host = () => test.info().project.use.baseURL ?? "http://127.0.0.1:3000";

/** window.open on the HOST page, recorded (the host opens allowed links). */
async function spyOnOpen(page: Page) {
  await page.addInitScript(() => {
    const w = window as unknown as { __opened: string[] };
    w.__opened = [];
    const real = window.open.bind(window);
    window.open = (url?: string | URL, ...rest: unknown[]) => {
      w.__opened.push(String(url));
      return real(url, ...(rest as [string?, string?]));
    };
  });
}

async function openHostile(page: Page, over: BridgeOptions = {}) {
  await spyOnOpen(page);
  const bridge = await installFakeBridge(page, {
    apps: [
      demoApp({
        id: "hostile",
        name: "Hostile",
        sources: ["calendar", "inbox"],
        script: hostileScript(listener, host()),
        body: "<main><p>hostile</p></main>",
      }),
    ],
    ...over,
  });
  await page.context().route("https://github.com/**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "text/html",
      body: "<p>stub</p>",
    }),
  );
  await page.goto("/workspace/apps/hostile");
  const handle = await page
    .locator('[data-testid="app-frame"]')
    .elementHandle();
  const frame = (await handle!.contentFrame())!;
  await expect
    .poll(() => frame.evaluate(() => document.body?.dataset.attacked ?? ""))
    .toBe("1");
  await expect
    .poll(() =>
      frame.evaluate(() =>
        Boolean((window as unknown as { __port?: unknown }).__port),
      ),
    )
    .toBe(true);
  return { bridge, frame };
}

interface Attack {
  tried: string[];
  errors: Record<string, string>;
  secrets: Record<string, unknown>;
}
const attackOf = (frame: Frame) =>
  frame.evaluate(() => (window as unknown as { __attack: Attack }).__attack);

/** Let any request that was going to leave, leave. */
const drain = (page: Page) => page.waitForTimeout(1500);

test("nothing leaves the frame: every channel in FR-018 reaches no server", async ({
  page,
  context,
}) => {
  const { bridge, frame } = await openHostile(page);
  await drain(page);
  const attack = await attackOf(frame);
  expect(attack.tried).toEqual(
    expect.arrayContaining([
      "fetch",
      "fetch-host-api",
      "xhr",
      "websocket",
      "eventsource",
      "beacon",
      "img",
      "img-tag",
      "css-url",
      "link-prefetch",
      "form",
      "window-open",
      "target-blank",
      "top-navigation",
      "nested-iframe",
      "worker",
      "blob-worker",
      "object",
      "audio",
    ]),
  );
  expect(hits, "requests that reached the listener").toEqual([]);
  expect(
    bridge.log.fromFrame,
    "requests the frame made to this origin",
  ).toEqual([]);
  // No popup, no top navigation.
  expect(context.pages()).toHaveLength(1);
  expect(page.url()).toMatch(/\/workspace\/apps\/hostile$/);
  // No cookie, no storage, no parent document; no WebRTC.
  expect(attack.secrets.cookie).toBeUndefined();
  expect(attack.errors.cookie).toBeTruthy();
  expect(attack.secrets.localStorage).toBeUndefined();
  expect(attack.secrets.sessionStorage).toBeUndefined();
  expect(attack.secrets.parentCookie).toBeUndefined();
  expect(attack.errors.parentDocument).toMatch(
    /SecurityError|cross-origin|Blocked/i,
  );
  expect(attack.secrets.rtc).toBe("undefined");
});

test("the sandbox attribute alone holds: no popup, form, top navigation or same-origin access", async ({
  page,
  context,
}) => {
  // The gateway's CSP without its own `sandbox` directive: only the host
  // page's iframe attribute is left to keep the frame opaque.
  const { frame } = await openHostile(page, { csp: "no-sandbox-directive" });
  await drain(page);
  const attack = await attackOf(frame);
  expect(hits).toEqual([]);
  expect(context.pages()).toHaveLength(1);
  expect(page.url()).toMatch(/\/workspace\/apps\/hostile$/);
  expect(attack.secrets.cookie).toBeUndefined();
  expect(attack.secrets.localStorage).toBeUndefined();
  expect(attack.secrets.parentCookie).toBeUndefined();
  expect(attack.secrets.popup).not.toMatch(/Window/);
});

test("the frame navigating itself off origin is refused by the host page's frame-src", async ({
  page,
}) => {
  const { frame } = await openHostile(page);
  await frame.evaluate(selfNavigateScript(listener));
  await drain(page);
  expect(hits).toEqual([]);
});

test("no token, cookie or stored value reaches the frame, in any host message", async ({
  page,
  context,
}) => {
  await context.addCookies([
    { name: "csrf_token", value: "CSRF-SENTINEL-1", url: host() },
    {
      name: "access_token",
      value: "ACCESS-SENTINEL-2",
      url: host(),
      httpOnly: true,
    },
  ]);
  await page.addInitScript(() => {
    try {
      localStorage.setItem("omni-secret", "LS-SENTINEL-3");
    } catch {}
  });
  // Even a bridge answer carrying an extra field is not forwarded.
  const { frame } = await openHostile(page, {
    resultExtra: { token: "BRIDGE-SENTINEL-4" },
  });
  await frame.evaluate(() => {
    const port = (window as unknown as { __port: MessagePort }).__port;
    port.postMessage({ v: 1, type: "data", id: "s1", source: "calendar" });
    port.postMessage({ v: 1, type: "refresh", id: "s2", source: "inbox" });
  });
  await expect
    .poll(async () =>
      JSON.stringify(
        await frame.evaluate(
          () => (window as unknown as { __omniLog: unknown[] }).__omniLog,
        ),
      ),
    )
    .toContain('"id":"s2"');
  const seen = JSON.stringify({
    log: await frame.evaluate(
      () => (window as unknown as { __omniLog: unknown[] }).__omniLog,
    ),
    attack: await attackOf(frame),
  });
  for (const sentinel of [
    "CSRF-SENTINEL-1",
    "ACCESS-SENTINEL-2",
    "LS-SENTINEL-3",
    "BRIDGE-SENTINEL-4",
  ]) {
    expect(seen, sentinel).not.toContain(sentinel);
  }
});

test("unapproved, write-ish, malformed and oversized requests are refused, answered and logged", async ({
  page,
}) => {
  const { bridge, frame } = await openHostile(page);
  const before = bridge.log.dataReads.length;
  await frame.evaluate(() => {
    const port = (window as unknown as { __port: MessagePort }).__port;
    const send = (m: unknown) => port.postMessage(m);
    send({ v: 1, type: "data", id: "a1", source: "inbox_bodies" });
    send({ v: 1, type: "data", id: "a2", source: "gmail_delete_message" });
    send({
      v: 1,
      type: "refresh",
      id: "a3",
      source: "calendar",
      params: { q: "in:sent" },
    });
    send({
      v: 1,
      type: "data",
      id: "a4",
      source: "calendar",
      pad: "x".repeat(9000),
    });
    send("give me everything");
    send({ v: 1, type: "init", app: "hostile", version: 3, theme: "dark" });
    send({ v: 1, type: "write", id: "a5", source: "calendar" });
  });
  await expect.poll(() => bridge.log.refused.length).toBeGreaterThanOrEqual(7);
  const expected = [
    "source_not_approved",
    "source_not_approved",
    "unknown_key:params",
    "too_large",
    "not_an_object",
    "unknown_type",
    "unknown_type",
  ];
  // Reports are separate requests: they may arrive in any order.
  expect(bridge.log.refused.map((r) => r.reason).sort()).toEqual(
    [...expected].sort(),
  );
  expect(bridge.log.refused).toContainEqual({
    reason: "source_not_approved",
    type: "data",
    source: "inbox_bodies",
  });
  // Nothing refused reached the bridge's data routes.
  expect(bridge.log.dataReads.slice(before)).toEqual([]);
  const log = (
    await frame.evaluate(
      () =>
        (
          window as unknown as {
            __omniLog: { type: string; id?: string; reason?: string }[];
          }
        ).__omniLog,
    )
  ).filter((m) => m.type === "error");
  expect(log.map((m) => m.reason)).toEqual(expected);
  expect(log[0]).toEqual({
    v: 1,
    type: "error",
    id: "a1",
    reason: "source_not_approved",
  });
});

test("a flood: at most 30 messages a second are served, the refusal is reported once", async ({
  page,
}) => {
  const { bridge, frame } = await openHostile(page);
  const before = bridge.log.dataReads.length;
  await frame.evaluate(() => {
    const port = (window as unknown as { __port: MessagePort }).__port;
    for (let i = 0; i < 300; i++) {
      port.postMessage({
        v: 1,
        type: "refresh",
        id: `f${i}`,
        source: "calendar",
      });
    }
  });
  await page.waitForTimeout(1500);
  const served = bridge.log.dataReads.length - before;
  expect(served).toBeGreaterThan(0);
  expect(served).toBeLessThanOrEqual(60); // two windows at most in 1.5 s
  const rate = bridge.log.refused.filter((r) => r.reason === "rate_limited");
  expect(rate.length).toBeGreaterThanOrEqual(1);
  expect(rate.length).toBeLessThanOrEqual(3);
});

test("messages outside the port are ignored: from the frame's window, or another window", async ({
  page,
}) => {
  const { bridge, frame } = await openHostile(page);
  const before = bridge.log.dataReads.length;
  // The frame posts to the host's window instead of its port.
  await frame.evaluate(() =>
    parent.postMessage(
      { v: 1, type: "data", id: "w1", source: "calendar" },
      "*",
    ),
  );
  // Another window on this page (a same-origin iframe) posts to the host.
  await page.evaluate(() => {
    const other = document.createElement("iframe");
    other.style.display = "none";
    document.body.appendChild(other);
    const doc = other.contentDocument!;
    const s = doc.createElement("script");
    s.textContent =
      'parent.postMessage({ v: 1, type: "data", id: "w2", source: "calendar" }, "*");';
    doc.body.appendChild(s);
  });
  await expect
    .poll(() => bridge.log.refused.map((r) => r.reason).sort())
    .toEqual(["not_on_port", "wrong_window"]);
  expect(bridge.log.dataReads.slice(before)).toEqual([]);
});

test("the shim ignores a forged init and forged results from other windows", async ({
  page,
}) => {
  await installFakeBridge(page, { apps: [demoApp()] });
  await page.addInitScript(() => {
    try {
      localStorage.setItem("theme", "light");
    } catch {}
  });
  await page.goto("/workspace/apps/today");
  const handle = await page
    .locator('[data-testid="app-frame"]')
    .elementHandle();
  const frame = (await handle!.contentFrame())!;
  await expect
    .poll(() => frame.evaluate(() => document.body?.dataset.rendered ?? ""))
    .toBe("all");
  // From another window: a forged init with its own port, and a forged
  // update on the window.
  await page.evaluate(() => {
    const app = document.querySelector<HTMLIFrameElement>(
      '[data-testid="app-frame"]',
    )!;
    const other = document.createElement("iframe");
    other.style.display = "none";
    document.body.appendChild(other);
    (window as unknown as { __appWin: Window | null }).__appWin =
      app.contentWindow;
    const doc = other.contentDocument!;
    const s = doc.createElement("script");
    s.textContent = `
      var ch = new MessageChannel();
      window.__forgedPort = ch.port1;
      window.__forgedHits = 0;
      ch.port1.onmessage = function(){ window.__forgedHits++; };
      parent.__appWin.postMessage({ v: 1, type: "init", app: "today", version: 3, theme: "dark" }, "*", [ch.port2]);
      parent.__appWin.postMessage({ v: 1, type: "update", source: "calendar", state: "failed", data: null, fetched_at: null, stale: false, reason: "FORGED" }, "*");
    `;
    doc.body.appendChild(s);
  });
  // And from the real parent: a second init after the handshake.
  await page.evaluate(() => {
    const app = document.querySelector<HTMLIFrameElement>(
      '[data-testid="app-frame"]',
    )!;
    const ch = new MessageChannel();
    (window as unknown as { __secondHits: number }).__secondHits = 0;
    ch.port1.onmessage = () => {
      (window as unknown as { __secondHits: number }).__secondHits++;
    };
    app.contentWindow!.postMessage(
      { v: 1, type: "init", app: "today", version: 3, theme: "dark" },
      "*",
      [ch.port2],
    );
  });
  await page.waitForTimeout(300);
  // The app asks for data again: it must go to the host's port only.
  await frame.evaluate(() => {
    void (
      window as unknown as { omni: { refresh(n: string): Promise<unknown> } }
    ).omni.refresh("calendar");
  });
  await page.waitForTimeout(500);
  expect(
    await frame.evaluate(() =>
      document.documentElement.classList.contains("dark"),
    ),
  ).toBe(false);
  await expect(frame.locator('[data-tile="calendar"]')).not.toContainText(
    "FORGED",
  );
  expect(
    await page.evaluate(
      () => (window as unknown as { __secondHits: number }).__secondHits,
    ),
  ).toBe(0);
  const forgedHits = await page.evaluate(() => {
    const other = document.querySelectorAll("iframe")[1]!;
    return (other.contentWindow as unknown as { __forgedHits: number })
      .__forgedHits;
  });
  expect(forgedHits).toBe(0);
});

test("a compromised frame cannot make the host open a link off the allowlist", async ({
  page,
  context,
}) => {
  const { bridge, frame } = await openHostile(page);
  await frame.evaluate((l) => {
    const port = (window as unknown as { __port: MessagePort }).__port;
    for (const url of [
      l + "/v/open-http",
      "https://evil.example/steal",
      "https://github.com.evil.example/",
      "javascript:alert(document.cookie)",
      "/api/apps",
      "//evil.example/x",
    ]) {
      port.postMessage({ v: 1, type: "open", url });
    }
    // A control: an allowed host does open.
    port.postMessage({
      v: 1,
      type: "open",
      url: "https://mail.google.com/mail/u/0/#inbox/abc",
    });
  }, listener);
  await drain(page);
  const opened = await page.evaluate(
    () => (window as unknown as { __opened: string[] }).__opened,
  );
  expect(opened).toEqual(["https://mail.google.com/mail/u/0/#inbox/abc"]);
  expect(
    bridge.log.refused.filter((r) => r.reason === "url_not_allowed"),
  ).toHaveLength(6);
  expect(hits).toEqual([]);
  expect(context.pages().map((p) => new URL(p.url()).host)).not.toContain(
    "evil.example",
  );
});

test("the app's own URL opened as a page: opaque, and it says to open it from OmniHarness", async ({
  page,
}) => {
  const bridge = await installFakeBridge(page, { apps: [demoApp()] });
  await page.goto("/api/apps/today/versions/3/app.html");
  await expect(page.locator("body")).toHaveText(
    "Open this app from OmniHarness.",
  );
  expect(await page.evaluate(() => origin)).toBe("null");
  expect(bridge.log.dataReads).toEqual([]);
});
