import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { deflateSync } from "node:zlib";

import type { Page, Route } from "@playwright/test";

/**
 * Spec 012 Slice 2: a fake gateway for code artifacts (html, react). It
 * serves the locked frame's document the way the gateway does: the
 * gateway's OWN shim (read from backend/app/gateway/artifacts_store/frame/
 * artifact-shim.js) injected as the first script, under the CSP and headers
 * of frame/profile.json (the one source both sides read). The gateway's
 * scan is NOT applied here on purpose: hostile documents reach the frame,
 * so these specs test the frame alone.
 *
 * ARTIFACT_SABOTAGE_FRAME (sabotage runs only): "open-connect" serves
 * connect-src *, "no-csp" serves no CSP, "no-shim" serves no shim.
 */

const FRAME_DIR = "../../../../backend/app/gateway/artifacts_store/frame/";
export const PROFILE = JSON.parse(
  readFileSync(new URL(FRAME_DIR + "profile.json", import.meta.url), "utf8"),
) as { csp_template: string; headers: Record<string, string>; sandbox: string };
const SHIM = () =>
  sabotageShim(
    readFileSync(
      new URL(FRAME_DIR + "artifact-shim.js", import.meta.url),
      "utf8",
    ),
  ).replace(/<\/script/gi, "<\\/script");

/** ARTIFACT_SABOTAGE_FRAME is a comma list (sabotage runs only). */
export function sabotage(name: string): boolean {
  return (process.env.ARTIFACT_SABOTAGE_FRAME ?? "").split(",").includes(name);
}

/** no-rtc-guard: WebRTC left in; no-frame-guard: frames allowed and kept;
 * old-shim-guards: the guards as they were (the value checked is not the
 * value written; shadow roots and srcdoc unguarded). */
function sabotageShim(text: string): string {
  if (sabotage("old-shim-guards"))
    text = text
      .replace(
        "var t = once(v); checkHtml([t]); desc.set.call(this, t);",
        "checkHtml([v]); desc.set.call(this, v);",
      )
      .replace(
        'try { Object.defineProperty(IFrameProto, "srcdoc"',
        "try { void (IFrameProto",
      )
      .replace(
        "if (observer) observer.observe(root",
        "if (false) observer.observe(root",
      )
      .replace(
        "function watchShadows(node) {",
        "function watchShadows(node) { return;",
      )
      .replace(
        'lock(Registry, "define", function',
        'void (Registry, "define", function',
      );
  const s = sabotage("no-rtc-guard")
    ? "no-rtc-guard"
    : sabotage("no-frame-guard")
      ? "no-frame-guard"
      : "";
  if (s === "no-rtc-guard")
    return text.replace(
      "for (var r = 0; r < RTC.length; r++) lock(w, RTC[r], undefined);",
      "",
    );
  if (s === "no-frame-guard")
    return text
      .replace(
        'throw new DOMException("Artifacts cannot create frames.", "NotSupportedError");',
        "return;",
      )
      .replace(
        "if (FRAME_TAGS[String(node.localName).toLowerCase()]) { node.remove(); continue; }",
        "continue;",
      );
  return text;
}

export const THREAD = "56565656-3434-1212-7878-909090909090";
const NOW = Date.now();
const iso = (s: number) => new Date(NOW + s * 1000).toISOString();

function png(rgb: [number, number, number], w = 64, h = 40): Buffer {
  const crc = (buf: Buffer) => {
    let c = ~0;
    for (const b of buf) {
      c ^= b;
      for (let k = 0; k < 8; k++) c = (c >>> 1) ^ (0xedb88320 & -(c & 1));
    }
    return ~c >>> 0;
  };
  const chunk = (type: string, data: Buffer) => {
    const len = Buffer.alloc(4);
    len.writeUInt32BE(data.length);
    const td = Buffer.concat([Buffer.from(type), data]);
    const c = Buffer.alloc(4);
    c.writeUInt32BE(crc(td));
    return Buffer.concat([len, td, c]);
  };
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(w, 0);
  ihdr.writeUInt32BE(h, 4);
  ihdr[8] = 8;
  ihdr[9] = 2;
  const rows = Buffer.alloc((w * 3 + 1) * h);
  for (let y = 0; y < h; y++)
    for (let x = 0; x < w; x++) rows.set(rgb, y * (w * 3 + 1) + 1 + x * 3);
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", ihdr),
    chunk("IDAT", deflateSync(rows)),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

export interface CodeRec {
  id: string;
  kind: "html" | "react" | "webapp";
  /** webapp: other pages by relative path. */
  pages?: Record<string, string>;
  title: string;
  html: string;
  check?: "passed" | "failed" | "not_checked" | "pending";
  buildFailed?: boolean;
  source?: { entry: string; files: Record<string, string> };
  summary?: string[];
}

/** As the gateway does it (artifacts_store/frame.py): the shim PREPENDED as
 * the first bytes after a leading doctype, never placed by parsing. */
export function frameDocument(html: string): string {
  if (sabotage("no-shim")) return html;
  const tag = `<script>${SHIM()}</script>`;
  if (sabotage("old-injection")) {
    // As before: placed by parsing (before the first script a comment-skipping
    // scan sees), so a script hidden from that scan runs first.
    const first = firstScriptAt(html);
    return first < 0
      ? html + tag
      : html.slice(0, first) + tag + html.slice(first);
  }
  const m = /^\uFEFF?[ \t\r\n\f]*<!doctype[^>]{0,1000}>/i.exec(html);
  return m ? m[0] + tag + html.slice(m[0].length) : tag + html;
}

function firstScriptAt(doc: string): number {
  let i = 0;
  for (;;) {
    i = doc.indexOf("<", i);
    if (i < 0) return -1;
    if (doc.startsWith("<!--", i)) {
      const j = doc.indexOf("-->", i + 4);
      if (j < 0) return -1;
      i = j + 3;
      continue;
    }
    if (/^<script[\s>]/i.test(doc.slice(i, i + 8))) return i;
    i += 1;
  }
}

/** As the gateway's tokenizer (apps/bundle.py `_comment_end`) and browsers
 * end a comment: "<!-->" and "<!--->" are complete, else the first "-->" or
 * "--!>"; unclosed, it runs to the end. */
function commentEnd(doc: string, i: number): number {
  if (doc.startsWith("<!-->", i)) return i + 5;
  if (doc.startsWith("<!--->", i)) return i + 6;
  const ends = [doc.indexOf("-->", i + 4), doc.indexOf("--!>", i + 4)].filter(
    (x) => x >= 0,
  );
  if (!ends.length) return doc.length;
  const at = Math.min(...ends);
  return at + (doc.startsWith("-->", at) ? 3 : 4);
}

/** The hashes of the inline scripts, found as the gateway's tokenizer finds
 * them (comments as above; script bodies up to the next "</script"). */
export function scriptHashes(doc: string): string[] {
  const out: string[] = [];
  let i = 0;
  for (;;) {
    i = doc.indexOf("<", i);
    if (i < 0) break;
    if (doc.startsWith("<!--", i)) {
      i = commentEnd(doc, i);
      continue;
    }
    const m = /^<script(\s[^>]*)?>/i.exec(doc.slice(i, i + 400));
    if (!m) {
      i += 1;
      continue;
    }
    const start = i + m[0].length;
    const end = doc.toLowerCase().indexOf("</script", start);
    const stop = end < 0 ? doc.length : end;
    if (!/\ssrc\s*=/i.test(m[1] ?? "")) {
      const h = createHash("sha256")
        .update(doc.slice(start, stop), "utf8")
        .digest("base64");
      if (!out.includes(h)) out.push(h);
    }
    i = stop;
  }
  return out;
}

/** The frame's CSP: the Apps profile template with the hashes (profile.json
 * keeps a copy of bundle.CSP_TEMPLATE; a backend test keeps them equal).
 * ARTIFACT_SABOTAGE_FRAME=loose-profile serves the earlier, looser profile. */
export function frameCsp(doc: string): string {
  const hashes =
    scriptHashes(doc)
      .map((h) => `'sha256-${h}'`)
      .join(" ") || "'none'";
  let csp = PROFILE.csp_template.replace("{scripts}", hashes);
  if (sabotage("loose-profile"))
    csp = csp
      .replace(/script-src [^;]+/, "script-src 'unsafe-inline'")
      .replace(
        "; require-trusted-types-for 'script'; trusted-types 'none'",
        "",
      );
  if (sabotage("open-connect"))
    csp = csp.replace("connect-src 'none'", "connect-src *");
  return csp;
}

export function frameHeaders(doc: string): Record<string, string> {
  return {
    ...PROFILE.headers,
    "Content-Type": "text/html; charset=utf-8",
    ...(sabotage("no-csp") ? {} : { "Content-Security-Policy": frameCsp(doc) }),
  };
}

const json = (body: unknown, status = 200) => ({
  status,
  contentType: "application/json",
  body: JSON.stringify(body),
});

function check(rec: CodeRec) {
  const state = rec.check ?? "passed";
  return {
    state,
    summary:
      rec.summary ??
      (state === "failed"
        ? ["overflows sideways at 360 px (light, dark)"]
        : []),
    failures:
      state === "failed"
        ? [
            "overflows sideways at 360 px (light) by 40 px (sticking out: div.wide)",
          ]
        : [],
    warnings: [],
    widths: [360, 560, 1280],
    themes: ["light", "dark"],
    shots: { light: state !== "not_checked", dark: state !== "not_checked" },
    checked_at: state === "pending" ? null : iso(-60),
  };
}

function summary(rec: CodeRec) {
  return {
    id: rec.id,
    kind: rec.kind,
    title: rec.title,
    latest_version: 1,
    version_count: 1,
    pinned: false,
    archived: false,
    archived_at: null,
    origin_thread_id: THREAD,
    origin_turn_id: "run-1",
    imported_from: null,
    lineage: "user",
    lineage_source: null,
    language: null,
    media_type: "text/html",
    size: rec.html.length,
    created_at: iso(-3600),
    updated_at: iso(-60),
    code: {
      build_state: rec.buildFailed ? "build_failed" : "ok",
      check_state: rec.buildFailed ? null : (rec.check ?? "passed"),
      shown_version: rec.buildFailed ? null : 1,
      build: null,
    },
  };
}

function version(rec: CodeRec) {
  return {
    n: 1,
    content_hash: "b".repeat(64),
    size: rec.html.length,
    media_type: "text/html",
    language: null,
    lineage: "user",
    lineage_source: null,
    origin: "tool",
    base_version: null,
    note: "A small page",
    thread_id: THREAD,
    turn_id: "run-1",
    tool_call_id: `call-${rec.id}`,
    stored: "blob",
    created_at: iso(-3600),
    code: {
      build_state: rec.buildFailed ? "build_failed" : "ok",
      has_source: rec.kind === "react",
      findings: [],
      fix_of: null,
      recipe: rec.kind === "react" ? { tool: "esbuild" } : { tool: "none" },
      check: rec.buildFailed ? null : check(rec),
    },
  };
}

export interface CodeLog {
  frames: { path: string; dest: string | undefined }[];
  refused: unknown[];
  writes: { path: string; body: unknown }[];
}

export async function installCodeStore(
  page: Page,
  recs: CodeRec[],
): Promise<CodeLog> {
  const log: CodeLog = { frames: [], refused: [], writes: [] };
  const find = (id: string) => recs.find((r) => r.id === id);
  await page.route(/\/api\/artifacts(\/|\?|$)/, async (route: Route) => {
    const req = route.request();
    const url = new URL(req.url());
    const path = url.pathname;
    const method = req.method();
    if (method !== "GET")
      log.writes.push({
        path,
        body: req.postData() ? (req.postDataJSON() as unknown) : null,
      });
    if (path === "/api/artifacts")
      return route.fulfill(
        json({
          artifacts: recs.map(summary),
          total: recs.length,
          usage: { used: 1000, cap: 1073741824 },
        }),
      );
    if (path.startsWith("/api/artifacts/threads/"))
      return route.fulfill(json({ artifacts: [] }));
    if (path === "/api/artifacts/usage")
      return route.fulfill(json({ used: 1000, cap: 1073741824 }));
    const m = /^\/api\/artifacts\/([^/]+)(?:\/(.*))?$/.exec(path);
    const rec = m ? find(m[1]!) : undefined;
    if (!m || !rec)
      return route.fulfill(
        json({ detail: { code: "artifact_not_found", message: "" } }, 404),
      );
    const rest = m[2] ?? "";
    if (method === "GET" && rest === "")
      return route.fulfill(json({ ...summary(rec), versions: [version(rec)] }));
    if (method === "GET" && rest === "versions/1")
      return route.fulfill(
        json({
          ...version(rec),
          content: rec.kind === "html" ? rec.html : null,
          source: rec.source ?? null,
          ...(rec.kind === "webapp"
            ? {
                entry: "index.html",
                files: ["index.html", ...Object.keys(rec.pages ?? {})].map(
                  (p) => ({ path: p, size: 100, media_type: "text/html" }),
                ),
                pages: ["index.html", ...Object.keys(rec.pages ?? {})].map(
                  (p) => ({ path: p, ok: true, reason: null }),
                ),
              }
            : {}),
          build_log: rec.buildFailed
            ? "src/App.tsx:1:1: ERROR: Unexpected"
            : null,
        }),
      );
    if (method === "GET" && rest === "versions/1/frame-token") {
      if (rec.buildFailed)
        return route.fulfill(
          json({ detail: { code: "build_failed", message: "" } }, 409),
        );
      return route.fulfill(
        json({
          token: "tok",
          expires_in: 300,
          url: `/api/artifacts/${rec.id}/versions/1/frame.html?t=tok-${rec.id}`,
        }),
      );
    }
    if (method === "GET" && rest === "versions/1/frame.html") {
      const headers = await req.allHeaders();
      log.frames.push({
        path: path + url.search,
        dest: headers["sec-fetch-dest"],
      });
      if (url.searchParams.get("t") !== `tok-${rec.id}`)
        return route.fulfill({
          status: 403,
          body: "Open this artifact in OmniHarness.",
        });
      const page = url.searchParams.get("path");
      const html = page === null ? rec.html : rec.pages?.[page];
      if (html === undefined)
        return route.fulfill({
          status: 404,
          body: "Open this artifact in OmniHarness.",
        });
      const doc = frameDocument(html);
      return route.fulfill({
        status: 200,
        headers: frameHeaders(doc),
        body: doc,
      });
    }
    const shot = /^versions\/1\/shots\/(light|dark)\.png$/.exec(rest);
    if (method === "GET" && shot)
      return route.fulfill({
        status: 200,
        headers: { "Content-Type": "image/png" },
        body: png(shot[1] === "dark" ? [40, 44, 60] : [210, 222, 255]),
      });
    if (method === "POST" && rest === "refused") {
      log.refused.push(req.postDataJSON());
      return route.fulfill({ status: 204, body: "" });
    }
    if (method === "POST" && rest === "versions/1/check")
      return route.fulfill(json({ state: "pending" }, 202));
    if (method === "POST" && rest === "rebuild")
      return route.fulfill(json({ build: null }, 202));
    return route.fulfill(
      json({ detail: { code: "artifact_not_found", message: "" } }, 404),
    );
  });
  return log;
}

/** A chat whose turns made these code artifacts (one card each). */
export async function installCodeThread(page: Page, recs: CodeRec[]) {
  const messages: unknown[] = [
    {
      type: "human",
      id: "h1",
      content: "Make me a small web page and a react counter.",
    },
  ];
  recs.forEach((r, i) => {
    messages.push(
      {
        type: "ai",
        id: `ai-${i}`,
        content: "",
        tool_calls: [
          {
            id: `c${i}`,
            name: "artifact_create",
            args: { kind: r.kind, title: "…" },
          },
        ],
      },
      {
        type: "tool",
        id: `t-${i}`,
        name: "artifact_create",
        tool_call_id: `c${i}`,
        content: `Created ${r.kind} artifact ${r.id} version 1.`,
        artifact: {
          type: "omni_artifact",
          artifact_id: r.id,
          version: 1,
          kind: r.kind,
        },
      },
      { type: "ai", id: `a-${i}`, content: `Here it is (${i + 1}).` },
    );
  });
  const state = {
    values: { title: "Code artifacts", messages },
    next: [],
    tasks: [],
    metadata: {},
    created_at: new Date().toISOString(),
    checkpoint: { thread_id: THREAD, checkpoint_id: "c1", checkpoint_ns: "" },
    parent_checkpoint: null,
  };
  await page.route("**/api/langgraph/**", (route) => {
    const u = route.request().url();
    if (u.includes("/history")) return route.fulfill(json([state]));
    if (u.includes("/runs") || u.includes("/search"))
      return route.fulfill(json([]));
    return route.fulfill(json(state));
  });
  await page.route("**/api/confirmations", (route) =>
    route.fulfill(json({ actions: [], readable: true, error: "" })),
  );
  await page.route("**/api/inbox/alerts", (route) =>
    route.fulfill(json({ alerts: [], waiting_count: 0 })),
  );
  await page.route("**/api/threads/*/artifacts/manifests", (route) =>
    route.fulfill(json({ manifests: [] })),
  );
}

export const CLEAN_PAGE = `<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><style>
body{margin:0;font:15px/1.5 system-ui,sans-serif;background:var(--background);color:var(--foreground)}
main{padding:20px;max-width:640px;margin:auto}
.card{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:16px}
button{background:var(--primary);color:var(--primary-foreground);border:0;border-radius:8px;padding:8px 14px;font:inherit}
</style></head><body><main><div class="card"><h1>Tip calculator</h1><p>Bill: <b id="b">$48.00</b></p>
<button id="go">Add 18%</button> <span id="out"></span>
<p><a href="https://example.org/help">Help</a></p></div></main>
<script>document.getElementById('go').onclick=function(){document.getElementById('out').textContent='$56.64'};</script></body></html>`;
