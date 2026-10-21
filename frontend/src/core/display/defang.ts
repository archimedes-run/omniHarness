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
  try {
    return new URL(url, APP_BASE).origin === APP_ORIGIN;
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
    host = new URL(url, APP_BASE).host;
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
