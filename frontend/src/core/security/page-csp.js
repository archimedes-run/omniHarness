/**
 * The page Content-Security-Policy, shared by next.config.js (every page) and
 * src/proxy.ts (the Apps pages, whose frame-src needs the request's host).
 * Plain JavaScript so next.config.js can import it.
 */

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
 * `frameSrc`: "'self' blob:" for most pages (artifact previews); the Apps
 * pages pass this origin's /api/apps/ only (Spec 011 FR-017).
 *
 * Applied to pages only, not /api/* or /mock/api/*: those serve the
 * gateway's responses and artifacts (an app preview the user built, a demo
 * thread's HTML), which run in the artifact iframe; frame-ancestors 'none'
 * would break that, and their own loads are not the app's.
 */
export function contentSecurityPolicy({ frameSrc = "'self' blob:" } = {}) {
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
    `frame-src ${frameSrc}`,
    "worker-src 'self' blob:",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ].join("; ");
}
