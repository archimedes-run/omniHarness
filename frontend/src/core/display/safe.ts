/**
 * THE frontend display sanitiser for agent- and content-derived text: the
 * mirror of backend/app/gateway/display_safe.py (same rules, same case file:
 * tests/unit/display-safe-cases.json).
 *
 * Which side does it: the backend sends every field it formats already
 * sanitised; the frontend applies the same rules again (idempotently) to
 * those fields and to text it receives raw, such as chat messages and
 * notifications. tests/unit/display-render-paths.test.ts lists the
 * components that render such text and fails if one stops using this.
 *
 * Rules: control and format characters go (C0/C1 controls, U+2028/2029,
 * bidi embeddings, overrides, isolates and marks, zero-width characters); a
 * line break becomes a space; URLs and bare domains are defanged
 * (hxxps://evil[.]example). Only links the app builds itself are live.
 */

const BREAKS = new RegExp(
  "[\\n\\r\\u2028\\u2029\\u000b\\u000c\\u0085\\t]",
  "g",
);
const INVISIBLE = /[\p{Cc}\p{Cf}]/gu;
const URL = /\b(h)(ttps?|xxps?)(:\/\/)([^\s<>"'“”]+)/gi;
const BARE_DOT = /(?<!\[)\.(?!\])/g;
const TLDS =
  "com|net|org|io|ai|co|dev|app|info|biz|me|us|uk|de|ru|cn|fr|xyz|site|online|top|example|test|local|sh|gg|ly|to|cc|tv|link|click|zip|mov";
const DOMAIN = new RegExp(`\\b((?:[a-z0-9-]+\\.)+(?:${TLDS}))\\b`, "gi");

function strip(text: string): string {
  return text
    .replace(BREAKS, " ")
    .replace(INVISIBLE, "")
    .split(/\s+/)
    .filter(Boolean)
    .join(" ");
}

export function defang(text: string): string {
  const urls = text.replace(
    URL,
    (_m, _h: string, scheme: string, _sep: string, rest: string) => {
      const slash = rest.indexOf("/");
      const host = slash === -1 ? rest : rest.slice(0, slash);
      const path = slash === -1 ? "" : rest.slice(slash);
      return `hxx${scheme.slice(2).toLowerCase()}://${host.replace(BARE_DOT, "[.]")}${path}`;
    },
  );
  return urls.replace(DOMAIN, (domain: string) => domain.replace(/\./g, "[.]"));
}

/** One line of agent- or content-derived text, safe to display anywhere. */
export function safeField(text: string | null | undefined): string {
  return defang(strip(text ?? ""));
}

/** A block whose line structure the app chose: each line made safe. */
export function safeLines(text: string | null | undefined): string {
  return (text ?? "")
    .split("\n")
    .map((line) => safeField(line))
    .join("\n");
}

const GITHUB_PR =
  /^https:\/\/github\.com\/[A-Za-z0-9-]{1,39}\/[A-Za-z0-9._-]{1,100}\/pull\/[0-9]{1,9}$/;
const GCAL =
  /^https:\/\/(calendar\.google\.com\/calendar\/|www\.google\.com\/calendar\/)[A-Za-z0-9/?=&%._~+-]*$/;

/** A link stays LIVE only when it provably is the provider's own link for
 *  the item (mirror of display_safe.provider_link); otherwise null, and the
 *  item is shown as safe text. */
export function providerLink(
  source: string,
  url: string | null | undefined,
): string | null {
  const text = url ?? "";
  if (source === "github" && GITHUB_PR.test(text)) return text;
  if (source === "calendar" && GCAL.test(text)) return text;
  return null;
}
