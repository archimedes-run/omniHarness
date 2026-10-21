/**
 * Run `build` or `dev` with `SKIP_ENV_VALIDATION` to skip env validation. This is especially useful
 * for Docker builds.
 */
import "./src/env.js";

function getInternalServiceURL(envKey, fallbackURL) {
  const configured = process.env[envKey]?.trim();
  return configured && configured.length > 0
    ? configured.replace(/\/+$/, "")
    : fallbackURL;
}
import nextra from "nextra";

/**
 * Content-Security-Policy (zero-click exfiltration fix, second line). The chat
 * renders agent text, and text an email or page planted can name an outside
 * URL; core/streamdown/content-url-guard.ts stops the renderer fetching it,
 * and this stops the browser if anything slips past: images and connections
 * go to this origin only.
 *
 * What the app needs, checked: fonts are self-hosted (public/fonts, katex's
 * from the bundle); no analytics or CDN; shiki runs its JavaScript regex
 * engine (no WebAssembly); artifact and preview iframes are this origin's
 * /api paths or blob: URLs. Next's inline bootstrap scripts need
 * 'unsafe-inline' (no nonce middleware here); `next dev` also needs eval.
 * A NEXT_PUBLIC_*_BASE_URL on another origin is added to connect-src, since
 * the browser then talks to it directly.
 *
 * Applied to pages only, not /api/* or /mock/api/*: those serve the
 * gateway's responses and artifacts (an app preview the user built, a demo
 * thread's HTML), which run in the artifact iframe; frame-ancestors 'none'
 * would break that, and their own loads are not the app's.
 */
function contentSecurityPolicy() {
  const dev = process.env.NODE_ENV !== "production";
  const connect = new Set(["'self'"]);
  for (const key of [
    "NEXT_PUBLIC_BACKEND_BASE_URL",
    "NEXT_PUBLIC_LANGGRAPH_BASE_URL",
  ]) {
    const value = process.env[key]?.trim();
    if (!value) continue;
    try {
      connect.add(new URL(value).origin);
    } catch {
      // A relative path: this origin, already allowed.
    }
  }
  return [
    "default-src 'self'",
    `script-src 'self' 'unsafe-inline'${dev ? " 'unsafe-eval'" : ""}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self' data:",
    `connect-src ${[...connect].join(" ")}`,
    "media-src 'self' data: blob:",
    "frame-src 'self' blob:",
    "worker-src 'self' blob:",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ].join("; ");
}

const withNextra = nextra({});

/** @type {import("next").NextConfig} */
const config = {
  i18n: {
    locales: ["en", "zh"],
    defaultLocale: "en",
  },
  devIndicators: false,
  experimental: {
    // `next dev` only. Turbopack's on-disk dev cache grew to 4 GB, was read
    // back at every boot, and the dev container was OOM-killed in a loop on a
    // 7.75 GiB Docker VM (Phase 2.5). Without it, a restart compiles routes
    // from scratch, which dev mode does on first visit anyway.
    turbopackFileSystemCacheForDev: false,
  },
  async headers() {
    return [
      {
        source: "/((?!api/|mock/api/).*)",
        headers: [
          { key: "Content-Security-Policy", value: contentSecurityPolicy() },
          // No referrer to other sites; "same-origin", not "no-referrer",
          // which would also null the Origin of the app's own POSTs.
          { key: "Referrer-Policy", value: "same-origin" },
          { key: "X-Content-Type-Options", value: "nosniff" },
        ],
      },
    ];
  },
  async rewrites() {
    const rewrites = [];
    const gatewayURL = getInternalServiceURL(
      "OMNI_HARNESS_INTERNAL_GATEWAY_BASE_URL",
      "http://127.0.0.1:8001",
    );

    if (!process.env.NEXT_PUBLIC_LANGGRAPH_BASE_URL) {
      rewrites.push({
        source: "/api/langgraph",
        destination: `${gatewayURL}/api`,
      });
      rewrites.push({
        source: "/api/langgraph/:path*",
        destination: `${gatewayURL}/api/:path*`,
      });
    }

    if (!process.env.NEXT_PUBLIC_BACKEND_BASE_URL) {
      rewrites.push({
        source: "/api/agents",
        destination: `${gatewayURL}/api/agents`,
      });
      rewrites.push({
        source: "/api/agents/:path*",
        destination: `${gatewayURL}/api/agents/:path*`,
      });
      rewrites.push({
        source: "/api/skills",
        destination: `${gatewayURL}/api/skills`,
      });
      rewrites.push({
        source: "/api/skills/:path*",
        destination: `${gatewayURL}/api/skills/:path*`,
      });

      // Catch-all for remaining gateway API routes (models, threads, memory,
      // mcp, artifacts, uploads, suggestions, runs, etc.) that don't have
      // their own NEXT_PUBLIC_* env var toggle.
      //
      // NOTE: this must come AFTER the /api/langgraph rewrite above so that
      // LangGraph-compatible routes keep their public prefix while Gateway
      // receives its native /api/* paths.
      rewrites.push({
        source: "/api/:path*",
        destination: `${gatewayURL}/api/:path*`,
      });
    }

    return rewrites;
  },
};

export default withNextra(config);
