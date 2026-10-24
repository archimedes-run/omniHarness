import { defangHost } from "@/core/display/defang";
import { safeField } from "@/core/display/safe";

/**
 * Search results (web_search, image_search) as a tidy list, never raw JSON.
 *
 * The backend hands the model and the chat the same compact shape
 * (backend omniharness/tools/search_results.py):
 * `{"query": "...", "results": [{"title", "url", "snippet"}]}` (image_search
 * adds `image_url`). Older threads may still hold a provider's own JSON (a
 * bare list, or `{results: [...]}` with `content`/`href`/`link`), and a
 * result handed back after a confirmation is prefixed with a sentence; each
 * is read here.
 *
 * NOTHING HERE IS FETCHED: no image, no preview. Text goes through the
 * display sanitiser (safeField: no control characters, URLs and domains
 * defanged); the host is shown defanged; a link is kept only when it is
 * http(s), for an ordinary anchor the person may click.
 */
export interface SearchResultItem {
  /** Safe to display. */
  title: string;
  /** An http(s) URL for the anchor's href, or null (shown as text only). */
  href: string | null;
  /** The link's host, defanged ("food1[.]example"); "" when none. */
  host: string;
  /** One line of snippet, safe to display; "" when none. */
  snippet: string;
}

const SNIPPET_MAX = 160;

/** The URL, when it is an absolute http(s) URL; otherwise null. */
export function httpUrl(value: unknown): string | null {
  if (typeof value !== "string" || !value.trim()) return null;
  try {
    const url = new URL(value.trim());
    return url.protocol === "http:" || url.protocol === "https:"
      ? url.toString()
      : null;
  } catch {
    return null;
  }
}

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function first(item: Record<string, unknown>, keys: string[]): unknown {
  for (const key of keys) {
    if (item[key]) return item[key];
  }
  return undefined;
}

function parse(raw: string): unknown {
  try {
    return JSON.parse(raw);
  } catch {
    // A result handed back after a confirmation: a sentence, then the JSON.
    const start = raw.search(/[[{]/);
    const end = Math.max(raw.lastIndexOf("}"), raw.lastIndexOf("]"));
    if (start < 0 || end <= start) return null;
    try {
      return JSON.parse(raw.slice(start, end + 1));
    } catch {
      return null;
    }
  }
}

/** The list a search step shows, or null when `result` is not search results. */
export function parseSearchResults(result: unknown): SearchResultItem[] | null {
  const payload = typeof result === "string" ? parse(result) : result;
  const items = Array.isArray(payload)
    ? payload
    : payload &&
        typeof payload === "object" &&
        Array.isArray((payload as { results?: unknown }).results)
      ? (payload as { results: unknown[] }).results
      : null;
  if (!items) return null;
  const out: SearchResultItem[] = [];
  for (const raw of items) {
    if (!raw || typeof raw !== "object") continue;
    const item = raw as Record<string, unknown>;
    const href = httpUrl(
      first(item, ["url", "link", "href", "source_url", "image_url"]),
    );
    const title = safeField(text(first(item, ["title", "name"])));
    const snippet = safeField(
      text(first(item, ["snippet", "content", "body", "description"])),
    );
    if (!title && !href) continue;
    out.push({
      title,
      href,
      host: href ? defangHost(href) : "",
      snippet:
        snippet.length > SNIPPET_MAX
          ? `${snippet.slice(0, SNIPPET_MAX - 1).trimEnd()}…`
          : snippet,
    });
  }
  return out;
}
