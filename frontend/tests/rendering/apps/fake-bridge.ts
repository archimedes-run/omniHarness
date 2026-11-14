import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";

import type { Page, Request, Route } from "@playwright/test";

import { DEMO_BODY, DEMO_SCRIPT, DEMO_SOURCES, DEMO_STYLE } from "./demo-app";

/**
 * Spec 011: a fake bridge for the rendering specs. It serves the gateway's
 * Apps routes as specs/011-apps/api.md defines them, from mock fixtures, and
 * the app document with the exact headers of FR-016 (one sha256 per inline
 * script, computed here as registration computes it). No real account.
 *
 * Everything the page asks of it is logged (`log`), so specs assert on what
 * reached the "gateway": which sources were fetched, which refusals were
 * reported, what was approved, restored, revoked or pinned.
 *
 * The shim is read from src/core/apps/shim/omni-shim.js at each request, so
 * a shim edit takes effect without a rebuild of the app.
 *
 * APPS_SABOTAGE_FRAME_CSP (sabotage runs only): "open-connect-src" serves the
 * frame with connect-src * (dropping the directive alone changes nothing:
 * it falls back to default-src 'none'); "no-trusted-types" drops the Trusted
 * Types directives; "no-csp" serves it without a CSP.
 */

const SHIM_PATH = new URL(
  "../../../src/core/apps/shim/omni-shim.js",
  import.meta.url,
);

export const HASH_TODAY = "9f2c4e1a" + "7b3d5c60".repeat(7);
export const HASH_PENDING = "0a1b2c3d" + "4e5f6071".repeat(7);

export type FrameCsp = "full" | "no-sandbox-directive";

const sha256 = (text: string) =>
  createHash("sha256").update(text, "utf8").digest("base64");

/** The app document and its headers, as the gateway serves it (FR-016). */
export function appDocument({
  style,
  body,
  scripts,
  csp = "full",
  trustedTypes = true,
}: {
  style: string;
  body: string;
  scripts: string[];
  csp?: FrameCsp;
  /** The Trusted Types directives (H1: no HTML or script from strings). */
  trustedTypes?: boolean;
}): { html: string; headers: Record<string, string> } {
  const html =
    `<!doctype html><html lang="en"><head><meta charset="utf-8">` +
    `<meta name="viewport" content="width=device-width,initial-scale=1">` +
    `<title>app</title><style>${style}</style>` +
    `<script>${scripts[0]}</script></head><body>${body}` +
    scripts
      .slice(1)
      .map((s) => `<script>${s}</script>`)
      .join("") +
    `</body></html>`;
  const scriptSrc = scripts.map((s) => `'sha256-${sha256(s)}'`).join(" ");
  const directives = [
    "sandbox allow-scripts",
    "default-src 'none'",
    `script-src ${scriptSrc}`,
    "style-src 'unsafe-inline'",
    "img-src data: blob:",
    "font-src data:",
    "media-src 'none'",
    "connect-src 'none'",
    "frame-src 'none'",
    "child-src 'none'",
    "worker-src 'none'",
    "object-src 'none'",
    "manifest-src 'none'",
    "base-uri 'none'",
    "form-action 'none'",
    "frame-ancestors 'self'",
    "require-trusted-types-for 'script'",
    "trusted-types 'none'",
  ];
  let policy = directives;
  if (csp === "no-sandbox-directive") policy = directives.slice(1);
  const sabotage = process.env.APPS_SABOTAGE_FRAME_CSP;
  if (!trustedTypes || sabotage === "no-trusted-types") {
    policy = policy.filter((d) => !d.includes("trusted-types"));
  }
  if (sabotage === "open-connect-src") {
    policy = policy.map((d) =>
      d.startsWith("connect-src") ? "connect-src *" : d,
    );
  }
  const headers: Record<string, string> = {
    "Content-Type": "text/html; charset=utf-8",
    "Cache-Control": "private, max-age=31536000, immutable",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "Cross-Origin-Resource-Policy": "same-origin",
    "X-DNS-Prefetch-Control": "off",
    "Permissions-Policy":
      "camera=(), microphone=(), geolocation=(), payment=(), usb=(), clipboard-read=(), clipboard-write=()",
  };
  if (sabotage !== "no-csp") {
    headers["Content-Security-Policy"] = policy.join("; ");
  }
  return { html, headers };
}

const minutesAgo = (m: number) =>
  new Date(Date.now() - m * 60_000).toISOString();

const WORDS: Record<string, { use: string; words: string; hosts: string[] }> = {
  calendar: {
    use: "googlecalendar.events_today",
    words:
      "Read today's events from Google Calendar (title, start, end, all day), for the day in UTC",
    hosts: ["calendar.google.com"],
  },
  gh_review: {
    use: "github.pr_search",
    words:
      "Read open pull requests waiting on your review from GitHub (repo, number, title, updated time, link)",
    hosts: ["github.com"],
  },
  inbox: {
    use: "gmail.unread_subjects",
    words:
      "Read subjects of unread mail in Primary from the last 3 days, not from you (not bodies): how many, subject, received time, link",
    hosts: ["mail.google.com"],
  },
  ledger: {
    use: "omni.ledger.today",
    words:
      "Read Ledger tasks that moved today, are stuck or are overdue (task, project, status, due date, link)",
    hosts: [],
  },
};

export function sourceView(name: string) {
  const w = WORDS[name]!;
  return {
    name,
    use: w.use,
    words: w.words,
    fields: ["title"],
    params: {},
    refresh_s: 300,
    refresh_words: "Refreshes every 5 minutes while you use it",
    link_hosts: w.hosts,
    last_fetched_at: minutesAgo(4),
    last_state: "fresh",
    last_error: null,
  };
}

export type SourceStates = Partial<
  Record<string, "fresh" | "empty" | "not_connected" | "failed">
>;

/** Mock data per source, in the state asked for. */
export function sourceResult(name: string, state = "fresh") {
  const base = { source: name, fetched_at: minutesAgo(4), stale: false };
  if (state === "empty") {
    return {
      ...base,
      state,
      data:
        name === "inbox"
          ? { count: 0, count_capped: false, items: [] }
          : { items: [] },
      reason: null,
    };
  }
  if (state === "not_connected") {
    return { ...base, state, data: null, fetched_at: null, reason: null };
  }
  if (state === "failed") {
    return {
      ...base,
      state,
      data: null,
      fetched_at: null,
      reason: "The connector did not answer in time.",
    };
  }
  const data: Record<string, unknown> = {
    calendar: {
      items: [
        {
          title: "Design review",
          start: "2026-11-13T15:00:00Z",
          end: "2026-11-13T15:30:00Z",
          all_day: false,
        },
        {
          title: "1:1 with Sam",
          start: "2026-11-13T17:00:00Z",
          end: "2026-11-13T17:30:00Z",
          all_day: false,
        },
      ],
    },
    gh_review: {
      items: [
        {
          repo: "acme/web",
          number: 412,
          title: "Fix the date picker",
          updated_at: minutesAgo(30),
          link: "https://github.com/acme/web/pull/412",
        },
      ],
    },
    inbox: {
      count: 3,
      count_capped: false,
      items: [
        {
          subject: "Invoice for October",
          received_at: minutesAgo(60),
          link: "https://mail.google.com/mail/u/0/#inbox/abc",
        },
        {
          subject: "Re: launch plan",
          received_at: minutesAgo(90),
          link: "https://mail.google.com/mail/u/0/#inbox/def",
        },
      ],
    },
    ledger: {
      items: [
        {
          bucket: "overdue",
          task: "Write the release notes",
          project: "Launch",
          status: "doing",
          due_date: "2026-11-12",
          link: "/workspace/projects/p1",
        },
      ],
    },
  };
  return {
    ...base,
    state: "fresh",
    data: data[name] ?? { items: [] },
    reason: null,
  };
}

export interface FakeApp {
  id: string;
  name: string;
  description: string;
  version: number;
  hash: string;
  status: "approved" | "needs_approval" | "revoked";
  sources: string[];
  states?: SourceStates;
  /** A newer version waiting on the owner's button (api.md pending_version). */
  pendingVersion?: number;
  /** The card's suggestion line (api.md suggestion_words). */
  suggestion?: { source: string; words: string };
  /** GET /api/apps/{id} answers 500 bridge_failed. */
  failDetail?: boolean;
  /** The app's own script (after the shim). Default: the demo app. */
  script?: string;
  style?: string;
  body?: string;
}

export function demoApp(over: Partial<FakeApp> = {}): FakeApp {
  return {
    id: "today",
    name: "Today",
    description: "My day at a glance (demo, mock data)",
    version: 3,
    hash: HASH_TODAY,
    status: "approved",
    sources: DEMO_SOURCES,
    ...over,
  };
}

export function pendingApp(over: Partial<FakeApp> = {}): FakeApp {
  return {
    id: "ci-board",
    name: "CI board",
    description: "Failing CI and recent merges",
    version: 1,
    hash: HASH_PENDING,
    status: "needs_approval",
    sources: ["gh_review", "inbox"],
    ...over,
  };
}

export interface BridgeLog {
  requests: { method: string; path: string; fromFrame: boolean }[];
  dataReads: string[];
  refused: { reason: string; type?: string; source?: string }[];
  approvals: unknown[];
  restores: unknown[];
  revokes: string[];
  pinWrites: string[][];
  /** Refusal reports the gateway would refuse (422): must stay empty. */
  invalidReports: unknown[];
  /** Requests the APP FRAME made to this origin (must stay empty). */
  fromFrame: string[];
}

export interface BridgeOptions {
  apps?: FakeApp[];
  pins?: string[];
  csp?: FrameCsp;
  /** Default true. False serves the CSP without its Trusted Types directives. */
  trustedTypes?: boolean;
  /** Serve the app without the platform shim (to test the CSP on its own). */
  withoutShim?: boolean;
  /** Extra JSON fields put on every bridge result (a leak the host must drop). */
  resultExtra?: Record<string, unknown>;
  /** Milliseconds each bridge answer waits. */
  delayMs?: number;
}

const json = (route: Route, body: unknown, status = 200) =>
  route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });

function isAppFrame(req: Request): boolean {
  try {
    return req.frame().url().includes("/app.html");
  } catch {
    return false;
  }
}

export function approvalCard(app: FakeApp, status = "pending") {
  return {
    id: `card${app.id.replace(/-/g, "")}`.padEnd(32, "0").slice(0, 32),
    app_id: app.id,
    app_name: app.name,
    version: app.pendingVersion ?? app.version,
    manifest_hash: app.hash,
    status,
    sources: app.sources.map((s) => ({
      name: s,
      words: WORDS[s]!.words,
      refresh_words: "Refreshes every 5 minutes while you use it",
    })),
    sentence: "Data is shown in the app only; the assistant never sees it.",
    suggestion: app.suggestion !== undefined,
    suggestion_source: app.suggestion?.source ?? null,
    suggestion_words: app.suggestion?.words ?? null,
    thread_id: "t1",
    created_at: minutesAgo(2),
    resolved_at: null,
  };
}

/** Install the fake bridge on a page. Returns the live log and state. */
export async function installFakeBridge(page: Page, opts: BridgeOptions = {}) {
  const apps = new Map(
    (opts.apps ?? [demoApp(), pendingApp()]).map((a) => [a.id, { ...a }]),
  );
  let pins = [...(opts.pins ?? [])];
  const log: BridgeLog = {
    requests: [],
    dataReads: [],
    refused: [],
    approvals: [],
    restores: [],
    revokes: [],
    pinWrites: [],
    invalidReports: [],
    fromFrame: [],
  };
  const wait = () =>
    opts.delayMs ? new Promise((r) => setTimeout(r, opts.delayMs)) : null;

  const summary = (a: FakeApp) => ({
    id: a.id,
    name: a.name,
    description: a.description,
    current_version: a.version,
    manifest_hash: a.hash,
    status: a.status,
    pinned: pins.includes(a.id),
    updated_at: minutesAgo(60 * 26),
    last_opened_at: a.id === "today" ? minutesAgo(12) : null,
    pending_version: a.pendingVersion ?? null,
  });
  const detail = (a: FakeApp) => ({
    ...summary(a),
    html_url: `/api/apps/${a.id}/versions/${a.version}/app.html`,
    sources: a.sources.map(sourceView),
    approval:
      a.status === "approved" && a.pendingVersion === undefined
        ? null
        : approvalCard(a),
  });
  const result = (a: FakeApp, s: string) => ({
    ...sourceResult(s, a.states?.[s] ?? "fresh"),
    ...(opts.resultExtra ?? {}),
  });

  await page.route("**/api/preferences/app-pins", async (route) => {
    const req = route.request();
    if (isAppFrame(req)) log.fromFrame.push(req.url());
    if (req.method() === "PUT") {
      pins = (req.postDataJSON() as { pins: string[] }).pins;
      log.pinWrites.push(pins);
    }
    return json(route, { pins });
  });

  await page.route(/\/api\/apps(\/|\?|$)/, async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const path = url.pathname;
    const method = req.method();
    const fromFrame = isAppFrame(req);
    log.requests.push({ method, path, fromFrame });
    if (fromFrame && !path.endsWith("/app.html")) log.fromFrame.push(req.url());
    await wait();

    if (path === "/api/apps") {
      return json(route, { apps: [...apps.values()].map(summary) });
    }
    if (path === "/api/apps/catalog") {
      return json(route, {
        entries: Object.values(WORDS).map((w) => ({
          id: w.use,
          kind: w.use.startsWith("omni.") ? "first_party" : "connector",
          toolkit: w.use.startsWith("omni.")
            ? null
            : w.use.split(".")[0]!.toUpperCase(),
          fields: [],
          params: {},
          link_hosts: w.hosts,
          default_refresh_s: 300,
        })),
        refresh_s: { default: 300, minimum: 60, maximum: 3600 },
      });
    }
    if (path === "/api/apps/approvals") {
      const thread = url.searchParams.get("thread_id");
      return json(route, {
        cards: [...apps.values()]
          .filter((a) => a.status !== "approved" && thread === "t1")
          .map((a) => approvalCard(a)),
      });
    }
    const m = /^\/api\/apps\/([a-z0-9-]+)(\/.*)?$/.exec(path);
    const app = m ? apps.get(m[1]!) : undefined;
    if (!m || !app) {
      return json(
        route,
        { detail: { code: "app_not_found", message: "No such app." } },
        404,
      );
    }
    const rest = m[2] ?? "";

    const html = /^\/versions\/(\d+)\/app\.html$/.exec(rest);
    if (html) {
      const shim = readFileSync(SHIM_PATH, "utf8");
      const appScript = app.script ?? DEMO_SCRIPT;
      const doc = appDocument({
        style: app.style ?? DEMO_STYLE,
        body: app.body ?? DEMO_BODY,
        // Without the shim, a placeholder takes its place in <head> so the
        // app's script still runs in <body>, as it would.
        scripts: opts.withoutShim
          ? ["/* no shim */", appScript]
          : [shim, appScript],
        csp: opts.csp ?? "full",
        trustedTypes: opts.trustedTypes ?? true,
      });
      return route.fulfill({
        status: 200,
        headers: doc.headers,
        body: doc.html,
      });
    }
    if (rest === "" && method === "GET") {
      if (app.failDetail) {
        return json(
          route,
          {
            detail: { code: "bridge_failed", message: "KeyError at app.py:42" },
          },
          500,
        );
      }
      return json(route, detail(app));
    }
    if (rest === "/data" || rest.startsWith("/data/")) {
      if (app.status !== "approved") {
        return json(
          route,
          {
            detail: {
              code: "not_approved",
              message: "This app's data sources have not been approved.",
            },
          },
          403,
        );
      }
      if (rest === "/data") {
        log.dataReads.push("*");
        return json(route, {
          app_id: app.id,
          version: app.version,
          results: Object.fromEntries(
            app.sources.map((s) => [s, result(app, s)]),
          ),
        });
      }
      const source = decodeURIComponent(rest.slice("/data/".length));
      log.dataReads.push(source);
      if (!app.sources.includes(source)) {
        return json(
          route,
          {
            detail: {
              code: "unknown_source",
              message: "Not in this app's manifest.",
            },
          },
          404,
        );
      }
      return json(route, result(app, source));
    }
    if (rest === "/refused" && method === "POST") {
      // api.md: codes only; anything else is 422 (and not logged).
      const body = req.postDataJSON() as Record<string, unknown>;
      const name = /^[a-z][a-z0-9_]{0,31}$/;
      const ok =
        typeof body.reason === "string" &&
        /^[a-z][a-z0-9_]{0,47}$/.test(body.reason) &&
        Object.keys(body).every((k) =>
          ["reason", "type", "source"].includes(k),
        ) &&
        (body.type === undefined ||
          (typeof body.type === "string" && name.test(body.type))) &&
        (body.source === undefined ||
          (typeof body.source === "string" && name.test(body.source)));
      if (!ok) {
        log.invalidReports.push(body);
        return json(
          route,
          { detail: [{ msg: "invalid refusal report" }] },
          422,
        );
      }
      log.refused.push(body as BridgeLog["refused"][number]);
      return route.fulfill({ status: 204, body: "" });
    }
    if (rest === "/approval") {
      return app.status === "approved" && app.pendingVersion === undefined
        ? json(
            route,
            {
              detail: {
                code: "no_pending_approval",
                message: "Nothing to approve.",
              },
            },
            404,
          )
        : json(route, approvalCard(app));
    }
    if (rest === "/approve" && method === "POST") {
      const body = req.postDataJSON() as {
        manifest_hash: string;
        card_id: string;
      };
      // The bridge's ApproveIn: exactly these two keys (extra="forbid").
      if (Object.keys(body).sort().join() !== "card_id,manifest_hash") {
        return json(route, { detail: [{ msg: "extra or missing keys" }] }, 422);
      }
      log.approvals.push(body);
      if (body.manifest_hash !== app.hash) {
        return json(
          route,
          { detail: { code: "hash_mismatch", message: "The app changed." } },
          409,
        );
      }
      app.status = "approved";
      if (app.pendingVersion !== undefined) {
        app.version = app.pendingVersion;
        delete app.pendingVersion;
      }
      return json(route, {
        status: "approved",
        manifest_hash: app.hash,
        approved_at: new Date().toISOString(),
      });
    }
    if (rest === "/versions") {
      return json(route, {
        current: app.version,
        versions: Array.from(
          { length: app.version },
          (_, i) => app.version - i,
        ).map((v) => ({
          version: v,
          at: minutesAgo(60 * 24 * (app.version - v + 1)),
          who: v === 1 ? "code_job" : "owner",
          source: "code_job",
          changed: v === 1 ? ["created"] : ["bundle"],
          manifest_hash: app.hash,
          approved: app.status === "approved",
          restored_from: null,
        })),
      });
    }
    if (rest === "/restore" && method === "POST") {
      const body = req.postDataJSON() as {
        to_version: number;
        base_version: number;
      };
      log.restores.push(body);
      if (body.base_version !== app.version) {
        return json(
          route,
          { detail: { code: "stale_version", message: "Stale." } },
          409,
        );
      }
      app.version += 1;
      return json(route, detail(app));
    }
    if (rest === "/permissions") {
      return json(route, {
        app_id: app.id,
        version: app.version,
        manifest_hash: app.hash,
        status: app.status,
        sentence: "Data is shown in the app only; the assistant never sees it.",
        sources: app.sources.map(sourceView),
        activity: [
          {
            at: minutesAgo(30),
            event: "app_message_refused",
            detail: { reason: "source_not_approved" },
          },
          {
            at: "2026-11-12T09:00:00+00:00",
            event: "app_approved",
            detail: { version: app.version, via: "button" },
          },
        ],
        grants:
          app.status === "needs_approval"
            ? []
            : [
                {
                  manifest_hash: app.hash,
                  approved_at: "2026-11-12T09:00:00+00:00",
                  revoked_at:
                    app.status === "revoked"
                      ? "2026-11-13T09:00:00+00:00"
                      : null,
                  version: app.version,
                },
              ],
      });
    }
    if (rest === "/revoke" && method === "POST") {
      log.revokes.push(app.id);
      const was = app.status;
      app.status = "revoked";
      return json(route, {
        status: "revoked",
        grants_ended: was === "approved" ? 1 : 0,
        cache_rows_deleted: was === "approved" ? app.sources.length : 0,
      });
    }
    return json(route, { detail: { code: "not_found", message: rest } }, 404);
  });

  return {
    log,
    apps,
    pins: () => pins,
  };
}
