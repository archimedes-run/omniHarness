import { readFile } from "node:fs/promises";
import { join } from "node:path";

import { MAX_SOURCE, MAX_SVG, mermaidConfig } from "@/core/artifacts/mermaid";
import { drawerMain } from "@/core/artifacts/mermaid-drawer";

/**
 * Spec 012 FR-015: the isolated mermaid frame (core/artifacts/mermaid.ts).
 *
 * frame.html: a document with its OWN policy: nothing loads or connects
 * except the two scripts below; inline styles only (mermaid writes them).
 * The page frames it with sandbox="allow-scripts" and no allow-same-origin,
 * so it runs as an opaque origin: no cookies, no access to the app, and a
 * diagram's CSS cannot fetch anything (img, font and connect are 'none').
 * next.config.js keeps the page policy off this path; this one replaces it.
 *
 * mermaid.js: the mermaid package's own self-contained bundle (MIT), read
 * from node_modules (the frontend runs `next start` from its own directory
 * with node_modules present). drawer.js: core/artifacts/mermaid-drawer.ts.
 */

const FRAME_CSP = [
  "default-src 'none'",
  "script-src 'self'",
  "style-src 'unsafe-inline'",
  "img-src data:",
  "font-src 'none'",
  "connect-src 'none'",
  "media-src 'none'",
  "object-src 'none'",
  "frame-src 'none'",
  "worker-src 'none'",
  "base-uri 'none'",
  "form-action 'none'",
  "frame-ancestors 'self'",
].join("; ");

const FRAME_HTML =
  '<!doctype html><html><head><meta charset="utf-8"><title>diagram</title></head>' +
  '<body style="margin:0"><script src="/mermaid-frame/mermaid.js"></script>' +
  '<script src="/mermaid-frame/drawer.js"></script></body></html>';

const COMMON = {
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "no-referrer",
  "Cache-Control": "public, max-age=3600",
};

let bundle: Promise<string> | null = null;
function mermaidBundle(): Promise<string> {
  bundle ??= readFile(
    join(process.cwd(), "node_modules", "mermaid", "dist", "mermaid.min.js"),
    "utf8",
  );
  return bundle;
}

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ file: string }> },
): Promise<Response> {
  const { file } = await params;
  if (file === "frame.html") {
    return new Response(FRAME_HTML, {
      headers: {
        ...COMMON,
        "Content-Type": "text/html; charset=utf-8",
        "Content-Security-Policy": FRAME_CSP,
      },
    });
  }
  if (file === "drawer.js") {
    const configs = {
      light: mermaidConfig(false),
      dark: mermaidConfig(true),
      maxSource: MAX_SOURCE,
      maxSvg: MAX_SVG,
    };
    const code = `"use strict";(${drawerMain.toString()})(${JSON.stringify(configs)});`;
    return new Response(code, {
      headers: { ...COMMON, "Content-Type": "text/javascript; charset=utf-8" },
    });
  }
  if (file === "mermaid.js") {
    try {
      return new Response(await mermaidBundle(), {
        headers: {
          ...COMMON,
          "Content-Type": "text/javascript; charset=utf-8",
        },
      });
    } catch {
      bundle = null;
      return new Response("", { status: 404 });
    }
  }
  return new Response("", { status: 404 });
}
