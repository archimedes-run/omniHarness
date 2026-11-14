/**
 * Spec 012 FR-015: a mermaid artifact drawn to an IMAGE, in an isolated frame.
 *
 * Mermaid lays a diagram out in a live document, and a diagram's own CSS
 * (classDef, style, a font face) goes live in that document. So mermaid
 * never runs in the app's page: it runs in an offscreen
 * `<iframe sandbox="allow-scripts">` (no allow-same-origin: an opaque origin
 * that holds no cookies and cannot reach the app) loading
 * /mermaid-frame/frame.html, whose own CSP is `default-src 'none'` with
 * scripts from that path only (src/app/mermaid-frame/[file]/route.ts). The
 * frame gets the source over a MessageChannel and answers with the SVG text
 * (mermaid-frame-host.ts); this side checks it against the SVG allowlist
 * (svg-allowlist.ts) and shows it ONLY as
 * `<img src="data:image/svg+xml;base64,…">`. Nothing of mermaid's touches
 * the app's document.
 *
 * Defence in depth before anything is sent: a directive naming
 * securityLevel, htmlLabels, secure or dompurifyConfig is refused (as the
 * gateway refuses it); CSS that can fetch (`url(`, `image-set(`, `image(`,
 * `@import`, `@font-face`) is refused anywhere; `\`, `{` and `}` are refused
 * in classDef, style, linkStyle and cssClass statements; `click`, `link`,
 * `callback` and `href` statements are removed (links in diagrams are not
 * supported); journey diagrams are not supported. The frame also runs mermaid strict, HTML labels off, with the
 * page-styling keys locked (`secure`).
 *
 * The steps take their dependencies (`deps`), so they are unit-tested
 * without a browser (tests/unit/artifacts-store.test.ts).
 */

export interface MermaidDeps {
  /** Draw in the isolated frame; resolves to mermaid's SVG text. */
  render: (source: string, dark: boolean) => Promise<string>;
  check: (svg: string) => { ok: true } | { ok: false; reason: string };
  toUrl: (svg: string) => string;
}

export type MermaidResult =
  | { ok: true; url: string; linksRemoved: boolean }
  | { ok: false; reason: string };

const LOCKED = [
  "secure",
  "securityLevel",
  "startOnLoad",
  "maxTextSize",
  "maxEdges",
  "suppressErrorRendering",
  "htmlLabels",
  "dompurifyConfig",
  "themeCSS",
  "fontFamily",
  "altFontFamily",
  "themeVariables",
  "flowchart",
  "theme",
  "darkMode",
];

export function mermaidConfig(dark: boolean): Record<string, unknown> {
  return {
    startOnLoad: false,
    securityLevel: "strict",
    htmlLabels: false,
    flowchart: { htmlLabels: false },
    suppressErrorRendering: true,
    maxTextSize: 50_000,
    theme: dark ? "dark" : "default",
    darkMode: dark,
    secure: LOCKED,
  };
}

export const MAX_SOURCE = 50_000;
export const MAX_SVG = 2_000_000;

const BANNED_DIRECTIVE =
  /%%\s*\{[\s\S]*?(securityLevel|htmlLabels|secure|dompurifyConfig)[\s\S]*?\}\s*%%/i;
const FETCHING_CSS = /url\s*\(|image-set\s*\(|\bimage\s*\(|@import|@font-face/i;
const STYLE_STATEMENT = /^\s*(classDef|style|linkStyle|cssClass)\b/i;
const LINK_STATEMENT = /^\s*(click|link|callback|href)\s/i;
/** Kinds mermaid draws with markup the allowlist refuses (journey writes
 * <switch> and foreignObject whatever the label setting). */
const UNSUPPORTED = /^\s*(journey)\b/i;
export const UNSUPPORTED_REASON = "unsupported diagram type";

export function refusedDirective(source: string): boolean {
  return BANNED_DIRECTIVE.test(source);
}

/** The pre-filter: a refusal, or the source with link statements removed. */
export function prefilter(
  source: string,
): { source: string; linksRemoved: boolean } | { refused: string } {
  if (source.length > MAX_SOURCE) return { refused: "too long" };
  if (refusedDirective(source))
    return { refused: "a directive that changes security" };
  if (FETCHING_CSS.test(source))
    return { refused: "CSS that loads a resource" };
  const first = source
    .split("\n")
    .find((l) => l.trim() && !l.trim().startsWith("%%"));
  if (first && UNSUPPORTED.test(first)) return { refused: UNSUPPORTED_REASON };
  let linksRemoved = false;
  const lines: string[] = [];
  for (const line of source.split("\n")) {
    if (STYLE_STATEMENT.test(line) && /[\\{}]/.test(line)) {
      return { refused: "a style statement with escapes or braces" };
    }
    if (LINK_STATEMENT.test(line)) {
      linksRemoved = true;
      continue;
    }
    lines.push(line);
  }
  return { source: lines.join("\n"), linksRemoved };
}

/** Draw one diagram (the frame draws one at a time). */
export async function drawMermaid(
  source: string,
  dark: boolean,
  deps: MermaidDeps,
): Promise<MermaidResult> {
  if (!source.trim()) return { ok: false, reason: "empty" };
  const pre = prefilter(source);
  if ("refused" in pre) return { ok: false, reason: pre.refused };
  try {
    const svg = await deps.render(pre.source, dark);
    if (typeof svg !== "string" || !svg)
      return { ok: false, reason: "no output" };
    if (svg.length > MAX_SVG) return { ok: false, reason: "too large" };
    const verdict = deps.check(svg);
    if (!verdict.ok) return { ok: false, reason: verdict.reason };
    return { ok: true, url: deps.toUrl(svg), linksRemoved: pre.linksRemoved };
  } catch {
    return { ok: false, reason: "mermaid could not draw it" };
  }
}
