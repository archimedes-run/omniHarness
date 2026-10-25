/**
 * What an outside link's label claims, against where the link goes.
 *
 * A label that reads as a URL or a domain must name the host the link
 * opens; otherwise the chat shows the URL the link really opens instead
 * (core/streamdown/content-url-guard.ts, components/workspace/citations/
 * external-link.tsx). The host a label names is found the way a browser would
 * read it: invisible characters dropped, surrounding punctuation trimmed, any
 * port, path, query or fragment ignored, and the host passed through the URL
 * parser, so full-width letters, ideographic full stops and look-alike
 * letters all come out as the host they really are (look-alikes as punycode).
 */

/** Control and format characters (bidi overrides, zero-width, soft hyphen…). */
export const INVISIBLE = /[\p{Cc}\p{Cf}]/gu;

/** Punctuation that wraps a domain in prose: "(good.example)," */
const WRAPPING = /^[\s"'“”‘’()[\]<>{},.;:!?]+|[\s"'“”‘’()[\]<>{},.;:!?]+$/g;

/** A dot as a browser reads it in a host: ".", "。", "．", "｡". */
const DOT = /[.。．｡]/;

/** A bare file name ("report.pdf"): read as a file, not a domain. Only
 *  extensions that are not also country domains people use. */
const FILE_NAME =
  /^[^./]+\.(pdf|txt|png|jpe?g|gif|svg|html?|csv|json|ya?ml|docx?|xlsx?|pptx?|[jt]sx?)$/i;

/** A label naming a URL with user info: never what it seems. */
export const USERINFO = "userinfo";

/** A label that reads as a domain but does not parse as one: read as
 *  misleading rather than trusted (fail closed). */
export const UNREADABLE = "unreadable";

/** A file name that is also a country domain ("README.md", "setup.py"):
 *  kept only when the link opens that very file. */
const AMBIGUOUS_FILE = /^[^./\s]+\.(md|py)$/i;

/** The host a label NAMES when it reads as a URL or a domain, USERINFO when
 *  it reads as a URL with user info, else null. */
export function labelHost(label: string): string | null {
  // NFKC folds look-alike dots ("․" ONE DOT LEADER, "…") and letters.
  let text = label
    .replace(INVISIBLE, "")
    .normalize("NFKC")
    .replace(WRAPPING, "");
  if (!text || /\s/.test(text)) return null;
  // A URL written without "//" ("https:good.example", "//good.example"):
  // read the host the way the browser would.
  if (!/^https?:\/\//i.test(text)) {
    text = text
      .replace(/^[a-z][a-z0-9+-]*:(?!\d+(?:[/?#]|$))/i, "")
      .replace(/^[/\\]+/, "");
  }
  let candidate = "";
  try {
    if (/^https?:\/\//i.test(text)) {
      const url = new URL(text);
      return url.username || url.password ? USERINFO : url.hostname;
    }
    // The URL parser drops any port, and maps full-width letters and dots.
    candidate = text.split(/[/?#]/, 1)[0]!;
    if (!DOT.test(candidate) || candidate.includes("@")) return null;
    if (FILE_NAME.test(candidate)) return null;
    const host = new URL(`http://${candidate}`).hostname;
    // A domain: dotted, ending in a letters-only (or punycode) label.
    return /\.([a-z]{2,63}|xn--[a-z0-9-]+)$/i.test(host) ? host : null;
  } catch {
    return DOT.test(candidate) ? UNREADABLE : null;
  }
}

/** A hostname, compared without a leading "www." or a trailing dot. */
export function bareHost(host: string): string {
  return host
    .toLowerCase()
    .replace(/\.$/, "")
    .replace(/^www\./, "");
}

/** True when a host is (partly) punycode: it holds non-ASCII letters that
 *  may look like other ones. */
export function isPunycode(host: string): boolean {
  return /(^|\.)xn--/i.test(host);
}

/**
 * True when `label` must not be shown for a link to `url`: it names a
 * different host, names a URL with user info, the link itself has user info,
 * or the label names the link's host in look-alike (punycode) letters.
 */
export function labelMisleads(label: string, url: URL): boolean {
  if (url.username || url.password) return true;
  const bare = label.replace(INVISIBLE, "").trim();
  if (
    AMBIGUOUS_FILE.test(bare) &&
    url.pathname.toLowerCase().endsWith(`/${bare.toLowerCase()}`)
  ) {
    return false;
  }
  const named = labelHost(label);
  if (named === null) return false;
  if (named === USERINFO || named === UNREADABLE) return true;
  return bareHost(named) !== bareHost(url.hostname) || isPunycode(url.hostname);
}

/** The URL as it reads truthfully: no user info ("good@evil" goes to evil),
 *  the host as the browser resolves it (punycode for look-alikes), no
 *  invisible characters. */
export function truthfulUrl(url: URL): string {
  return `${url.protocol}//${url.host}${url.pathname}${url.search}${url.hash}`.replace(
    INVISIBLE,
    "",
  );
}
