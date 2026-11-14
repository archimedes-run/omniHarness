import { NextResponse, type NextRequest } from "next/server";

import { appHostPolicy } from "@/core/security/app-host-csp";

/**
 * Spec 011: the Apps pages' Content-Security-Policy needs the request's own
 * host (frame-src scoped to its /api/apps/), which next.config.js headers
 * cannot know. nginx passes the browser's Host through.
 */
export function proxy(request: NextRequest) {
  const response = NextResponse.next();
  response.headers.set(
    "Content-Security-Policy",
    appHostPolicy(request.headers.get("host")),
  );
  return response;
}

export const config = {
  matcher: ["/workspace/apps", "/workspace/apps/:path*"],
};
