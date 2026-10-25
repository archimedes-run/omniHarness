/**
 * Content-derived URLs are shown, never fetched (the zero-click exfiltration
 * fix). Text the agent writes can carry a URL that an email or a web page it
 * read told it to write, with private data in the query string. A browser
 * fetches an <img src> the moment it renders; a defanged URL is just text.
 *
 * Only the app's own URLs (relative, same origin) are left live.
 */

/** A base no real URL shares, to tell "relative to this app" from "elsewhere". */
const APP_BASE = "https://app.invalid/";
const APP_ORIGIN = new URL(APP_BASE).origin;

/**
 * True when `url` resolves to this app's own origin: a relative path such as
 * `/api/threads/…/artifacts/…`, `/mnt/user-data/…` or `chart.png`. Parsed the
 * way the browser parses it, so `//host`, `/\host`, `ht\ntps://host` and
 * `javascript:` all count as elsewhere.
 */
export function isAppUrl(url: string): boolean {
  // Anything that names a scheme is absolute, whatever the base. Resolved
  // against a base with the same scheme, "https:host/p" would read as a
  // relative path here, yet on a page served over another scheme the browser
  // resolves it to https://host/p. The parser ignores whitespace and control
  // characters inside a scheme, so they are ignored for this check too.
  if (/^[a-z][a-z0-9+.-]*:/i.test(url.replace(/[\p{Cc}\p{Cf}\s]/gu, ""))) {
    try {
      return new URL(url).origin === APP_ORIGIN;
    } catch {
      return false;
    }
  }
  try {
    return new URL(url, APP_BASE).origin === APP_ORIGIN;
  } catch {
    return false;
  }
}

/** True for an absolute http(s) URL, as the browser parses it. */
export function isHttpUrl(url: string): boolean {
  try {
    const { protocol } = new URL(url);
    return protocol === "http:" || protocol === "https:";
  } catch {
    return false;
  }
}

/**
 * True for a URL that loads nothing over the network when used as an image
 * source: an inline `data:image/…` (an SVG loaded as an image cannot fetch
 * anything) or the app's own URL.
 */
export function isLocalImageUrl(url: string): boolean {
  return /^\s*data:image\//i.test(url) || isAppUrl(url);
}

/** The host a URL points at, defanged: `attacker[.]example`. "" when none. */
export function defangHost(url: string): string {
  let host = "";
  try {
    // A URL naming a scheme is absolute: never resolved against the app.
    host = (isAppUrl(url) ? new URL(url, APP_BASE) : new URL(url)).host;
  } catch {
    const m = /^[a-z][a-z0-9+.-]*:\/\/([^/?#\s]*)/i.exec(url.trim());
    host = m?.[1] ?? "";
  }
  return host.replaceAll(".", "[.]");
}

/**
 * The whole URL, readable and not clickable or linkifiable:
 * `https://attacker.example/c?d=x` → `hxxps://attacker[.]example/c?d=x`.
 */
export function defangUrl(url: string): string {
  const m = /^(\s*)([a-z][a-z0-9+.-]*):(\/\/)?([^/?#\s]*)(.*)$/is.exec(url);
  if (!m) return url.replaceAll(".", "[.]");
  const [, lead, scheme, slashes = "", host, rest] = m;
  const s = scheme!.toLowerCase();
  const fanged =
    s === "http" ? "hxxp" : s === "https" ? "hxxps" : `${scheme}[:]`;
  const sep = s === "http" || s === "https" ? ":" : "";
  return `${lead}${fanged}${sep}${slashes}${host!.replaceAll(".", "[.]")}${rest}`;
}
