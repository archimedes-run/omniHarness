import { NextResponse, type NextRequest } from "next/server";

import {
  appHostPolicy,
  workspaceHostPolicy,
} from "@/core/security/app-host-csp";

/**
 * The pages' Content-Security-Policy needs the request's own host: frame-src
 * is a list of path-scoped sources on it, which next.config.js headers
 * cannot know. nginx passes the browser's Host through.
 * - the Apps pages (Spec 011): this origin's /api/apps/ only;
 * - every other page (Spec 012 S2): page-csp.js FRAME_PATHS only. Never bare
 *   'self', never blob:, so a frame that navigates itself cannot reach a
 *   document of its own making or one without a shim.
 */
export function proxy(request: NextRequest) {
  const response = NextResponse.next();
  const host = request.headers.get("host");
  const path = request.nextUrl.pathname;
  const apps =
    path === "/workspace/apps" || path.startsWith("/workspace/apps/");
  response.headers.set(
    "Content-Security-Policy",
    apps
      ? appHostPolicy(host)
      : workspaceHostPolicy(host, {
          // Demo mode: the same flag the chat page reads (use-thread-chat).
          demo: request.nextUrl.searchParams.get("mock") === "true",
        }),
  );
  return response;
}

export const config = {
  // Every page; not the API, the mock API, the isolated mermaid frame (each
  // sets its own policy), Next's own assets or files with an extension.
  matcher: ["/((?!api/|mock/api/|mermaid-frame/|_next/|.*\\..*).*)"],
};
