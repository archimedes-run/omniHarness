import { createHmac } from "node:crypto";
import { existsSync, readFileSync, statSync } from "node:fs";
import { extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";

import type { Page, Request, Route } from "@playwright/test";

/**
 * The live preview's gateway side, for the rendering specs.
 *
 * Two modes:
 * - default (CI): a fake of the frame link. It mints tokens, refuses any it
 *   did not mint for that preview, serves the fixture app (apps/<name>) the
 *   way a dev server would, rewrites root-relative URLs onto the link and
 *   adds `<base>` the way the gateway does, under the headers of
 *   backend/app/gateway/preview_frame_profile.json (the one source both sides
 *   read). The gateway's script shim is NOT applied: tests that need it run
 *   in the second mode only.
 * - LIVE_PREVIEW_GATEWAY=http://127.0.0.1:<port>: the frame link and the
 *   link route go to the REAL gateway code (live-preview/gateway_harness.py,
 *   the previews router with the same fixture apps on real local dev
 *   servers).
 *
 * The rest of the gateway (sessions, logs, restart, and one owner-only API
 * route) is faked here in both modes.
 */

const HERE = fileURLToPath(new URL(".", import.meta.url));
export const APPS_DIR = join(HERE, "apps");
export const PROFILE = JSON.parse(
  readFileSync(
    join(HERE, "../../../../backend/app/gateway/preview_frame_profile.json"),
    "utf8",
  ),
) as { sandbox: string; headers: Record<string, string> };
export const REAL_GATEWAY = process.env.LIVE_PREVIEW_GATEWAY ?? "";
/** The gateway's in-memory storage stand-in, read from its source (the live
 * page gets it inline, first in its head). */
const STORAGE_SHIM = /PREVIEW_STORAGE_SHIM_JS = """([\s\S]*?)"""/.exec(
  readFileSync(
    join(HERE, "../../../../backend/app/gateway/routers/artifacts.py"),
    "utf8",
  ),
)![1]!;

/** The body of the owner-only API route (answered only with the session). */
export const OWNER_SECRET = "owner-secret-7f3a";

export type App = "vite-app" | "site" | "probe";
export const previewId = (app: App) => `preview_${app}`;

const TYPES: Record<string, string> = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript",
  ".css": "text/css",
  ".svg": "image/svg+xml",
  ".json": "application/json",
};

/** A dev server for one fixture app: files, an SPA fallback for the Vite
 * app, and an echo API. */
export function devServer(
  app: App,
  path: string,
  method: string,
  body: Buffer | null,
): { status: number; headers: Record<string, string>; body: Buffer } {
  const pathname = decodeURIComponent(path.split("?")[0] ?? "/");
  if (method === "POST" && pathname === "/api/echo")
    return {
      status: 200,
      headers: { "content-type": "application/json" },
      body: body ?? Buffer.from("{}"),
    };
  const root = join(APPS_DIR, app);
  let file = normalize(join(root, pathname));
  if (!file.startsWith(root))
    return { status: 404, headers: {}, body: Buffer.from("") };
  if (existsSync(file) && statSync(file).isDirectory())
    file = join(file, "index.html");
  if (!existsSync(file)) {
    if (app === "vite-app" && !extname(pathname))
      file = join(root, "index.html");
    else
      return {
        status: 404,
        headers: { "content-type": "text/plain" },
        body: Buffer.from("not found"),
      };
  }
  const type =
    TYPES[extname(file)] ??
    (pathname.startsWith("/@vite/") ? "text/javascript" : "text/plain");
  return {
    status: 200,
    headers: { "content-type": type },
    body: readFileSync(file),
  };
}

export interface LiveLog {
  minted: string[];
  /** Every request for the preview (the frame link, or the old cookie route
   * of an older build): path, whether it carried a cookie, its token. */
  live: { url: string; cookie: boolean; token: string; type: string }[];
  probe: { cookie: boolean }[];
  restarts: number;
}

const LIVE_RE =
  /^\/api\/threads\/([^/]+)\/previews\/([^/]+)\/live\/([^/]+)(\/.*)?$/;
/** The cookie route builds before the frame link had (for the reproduce run
 * against such a build): same-origin, no sandbox header. */
const OLD_PROXY_RE =
  /^\/api\/threads\/([^/]+)\/previews\/([^/]+)\/proxy(\/.*)?$/;

function fakeToken(n: number) {
  const sig = createHmac("sha256", "fake-live-preview")
    .update(String(n))
    .digest("base64url");
  return `v1.${2_000_000_000 + n}.${sig}`;
}

const ROOT_RELATIVE_ATTR =
  /(\b(?:href|src|poster|action)\s*=\s*["'])(\/(?!\/)[^"']*)(["'])/gi;
const ROOT_RELATIVE_IMPORT =
  /(\b(?:from|import)\s*\(?\s*["'])(\/(?!\/)[^"'\s]*)(["'])/g;

function frameHeaders(request: Request): Record<string, string> {
  const origin = request.headers().origin;
  const profile = { ...PROFILE.headers };
  // Sabotage runs only: the responses without their sandbox header.
  if ((process.env.LIVE_SABOTAGE ?? "").split(",").includes("no-header"))
    delete profile["Content-Security-Policy"];
  return {
    ...profile,
    ...(origin === "null"
      ? {
          "Access-Control-Allow-Origin": "null",
          "Access-Control-Allow-Credentials": "true",
          Vary: "Origin",
        }
      : { "Access-Control-Allow-Origin": "*" }),
  };
}

export async function installLivePreview(
  page: Page,
  {
    thread,
    apps,
    expiresInSeconds = 600,
  }: { thread: string; apps: App[]; expiresInSeconds?: number },
): Promise<LiveLog> {
  const log: LiveLog = { minted: [], live: [], probe: [], restarts: 0 };
  const json = (body: unknown) => ({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
  const now = new Date().toISOString();
  const session = (app: App) => ({
    id: previewId(app),
    user_id: "owner",
    thread_id: thread,
    artifact_id: app,
    root_path: `/mnt/user-data/workspace/${app}`,
    command: "npm run dev",
    port: 5173,
    status: "running",
    logs_url: `/api/threads/${thread}/previews/${previewId(app)}/logs`,
    // What builds before the frame link read (the gateway no longer sends it).
    proxy_url: `/api/threads/${thread}/previews/${previewId(app)}/proxy`,
    created_at: now,
    updated_at: now,
    expires_at: now,
  });
  const allowed = new Map<string, Set<string>>(
    apps.map((app) => [previewId(app), new Set<string>()]),
  );
  let n = 0;

  await page.route("**/api/threads/*/artifacts/manifests", (route) =>
    route.fulfill(
      json({
        manifests: apps.map((app) => ({
          id: app,
          title: `Live ${app}`,
          type: "web_app",
          root: ".",
          source_path: `/mnt/user-data/workspace/${app}`,
          preview: { mode: "dev_server", command: "npm run dev", port: 5173 },
          manifest_path: `/mnt/user-data/outputs/${app}/artifact_manifest.json`,
          root_path: `/mnt/user-data/outputs/${app}`,
          entrypoint_path: null,
        })),
      }),
    ),
  );
  await page.route(`**/api/threads/${thread}/previews`, (route) =>
    route.fulfill(json(apps.map(session))),
  );
  await page.route(`**/api/threads/${thread}/previews/*/logs`, (route) =>
    route.fulfill(
      json({
        preview_id: "x",
        thread_id: thread,
        status: "running",
        logs: "ready",
      }),
    ),
  );
  await page.route(`**/api/threads/${thread}/previews/*/restart`, (route) => {
    log.restarts += 1;
    const id = new URL(route.request().url()).pathname.split("/")[5]!;
    return route.fulfill(json(session(id.replace("preview_", "") as App)));
  });
  await page.route(`**/api/threads/${thread}/projects/*/files`, (route) =>
    route.fulfill(json({ artifact_id: "x", root: "/", files: [] })),
  );
  // On the context: a window the app opens (Open in new window) too.
  const context = page.context();
  // An owner-only API route: its body only with the session cookie.
  await context.route(
    (url) =>
      url.pathname === "/api/v1/auth/me" && url.searchParams.has("probe"),
    async (route) => {
      const cookie = (
        (await route.request().allHeaders()).cookie ?? ""
      ).includes("access_token=");
      log.probe.push({ cookie });
      return route.fulfill({
        status: cookie ? 200 : 401,
        contentType: "application/json",
        body: JSON.stringify(
          cookie ? { email: "owner@example.com", secret: OWNER_SECRET } : {},
        ),
      });
    },
  );
  await page.route(
    `**/api/threads/${thread}/previews/*/frame`,
    async (route) => {
      if (REAL_GATEWAY) {
        const response = await route.fetch({
          url: REAL_GATEWAY + new URL(route.request().url()).pathname,
        });
        const body = (await response.json()) as {
          frame_url: string;
          expires_at: string;
        };
        log.minted.push(body.frame_url);
        // A shorter life as the host sees it (the token itself keeps its own),
        // so the host asks again within the test.
        if (expiresInSeconds !== 600)
          body.expires_at = new Date(
            Date.now() + expiresInSeconds * 1000,
          ).toISOString();
        return route.fulfill({ response, json: body });
      }
      const id = new URL(route.request().url()).pathname.split("/")[5]!;
      n += 1;
      const token = fakeToken(n);
      allowed.get(id)?.add(token);
      const frameUrl = `/api/threads/${thread}/previews/${id}/live/${token}`;
      log.minted.push(frameUrl);
      return route.fulfill(
        json({
          frame_url: frameUrl,
          expires_at: new Date(
            Date.now() + expiresInSeconds * 1000,
          ).toISOString(),
        }),
      );
    },
  );
  await context.route(
    (url) => LIVE_RE.test(url.pathname),
    async (route: Route) => {
      const request = route.request();
      const url = new URL(request.url());
      const [, , id, token, rest] = LIVE_RE.exec(url.pathname)!;
      const headers = await request.allHeaders();
      log.live.push({
        url: url.pathname,
        cookie: (headers.cookie ?? "").includes("access_token="),
        token: token!,
        type: request.resourceType(),
      });
      if (REAL_GATEWAY) {
        const response = await route.fetch({
          url: REAL_GATEWAY + url.pathname + url.search,
          maxRedirects: 0,
        });
        const headers = response.headers();
        if ((process.env.LIVE_SABOTAGE ?? "").split(",").includes("no-header"))
          delete headers["content-security-policy"];
        return route.fulfill({ response, headers });
      }
      if (!allowed.get(id!)?.has(token!))
        return route.fulfill({ status: 404, body: "Preview not found" });
      if (
        request.method() === "OPTIONS" &&
        headers["access-control-request-method"]
      )
        return route.fulfill({
          status: 204,
          headers: {
            ...frameHeaders(request),
            "Access-Control-Allow-Methods":
              headers["access-control-request-method"],
            "Access-Control-Allow-Headers":
              headers["access-control-request-headers"] ?? "",
          },
        });
      const app = id!.replace("preview_", "") as App;
      const root = `/api/threads/${thread}/previews/${id}/live/${token}`;
      const served = serve(app, root, rest, url.search, request, true);
      return route.fulfill({
        ...served,
        headers: { ...served.headers, ...frameHeaders(request) },
      });
    },
  );
  await context.route(
    (url) => OLD_PROXY_RE.test(url.pathname),
    async (route: Route) => {
      const request = route.request();
      const url = new URL(request.url());
      const [, , id, rest] = OLD_PROXY_RE.exec(url.pathname)!;
      const cookie = ((await request.allHeaders()).cookie ?? "").includes(
        "access_token=",
      );
      log.live.push({
        url: url.pathname,
        cookie,
        token: "",
        type: request.resourceType(),
      });
      if (REAL_GATEWAY || !cookie)
        return route.fulfill({ status: 404, body: "Not Found" });
      const app = id!.replace("preview_", "") as App;
      const root = `/api/threads/${thread}/previews/${id}/proxy`;
      return route.fulfill(serve(app, root, rest, url.search, request, false));
    },
  );
  return log;
}

/** The dev server's answer as the gateway passes it on: root-relative URLs
 * onto the link, `<base>` (and, on the frame link, the storage stand-in). */
function serve(
  app: App,
  root: string,
  rest: string | undefined,
  search: string,
  request: Request,
  frame: boolean,
) {
  const served = devServer(
    app,
    (rest ?? "/") + search,
    request.method(),
    request.postDataBuffer(),
  );
  let body: Buffer | string = served.body;
  const type = served.headers["content-type"] ?? "";
  if (type.startsWith("text/html")) {
    const head = `<base href="${root}/" data-omni-preview>${frame ? `<script>${STORAGE_SHIM}</script>` : ""}`;
    body = served.body
      .toString("utf8")
      .replace(ROOT_RELATIVE_ATTR, `$1${root}$2$3`)
      .replace(/<head(\s[^>]*)?>/i, (m) => `${m}${head}`);
  } else if (type.includes("javascript")) {
    body = served.body
      .toString("utf8")
      .replace(ROOT_RELATIVE_IMPORT, `$1${root}$2$3`);
  } else if (type === "text/css") {
    body = served.body
      .toString("utf8")
      .replace(/url\((\/(?!\/)[^)]*)\)/g, `url(${root}$1)`);
  }
  return { status: served.status, headers: served.headers, body };
}
