/**
 * Spec 012 FR-015: a mermaid artifact drawn to an IMAGE.
 *
 * The isolated step: mermaid runs with securityLevel "strict" and HTML labels
 * off; the keys a diagram's own `%%{init}%%` directive could use to loosen
 * that (or restyle the page: themeCSS, fontFamily) are locked through
 * mermaid's `secure` list, and a directive naming securityLevel, htmlLabels,
 * secure or dompurifyConfig is refused outright (as the gateway refuses it).
 * It draws into an offscreen, inert container that is removed afterwards;
 * the SVG string it returns must pass the SVG allowlist (svg-allowlist.ts)
 * and is then shown ONLY as `<img src="data:image/svg+xml;base64,…">`.
 * Mermaid's markup is never placed in the page. On any failure the caller
 * shows the source as code with "Couldn't draw this diagram".
 *
 * Everything is injected (`deps`) so the steps are unit-tested without a
 * browser (tests/unit/artifacts-mermaid.test.ts).
 */

export interface MermaidLike {
  initialize(config: Record<string, unknown>): void;
  render(
    id: string,
    text: string,
    container?: Element,
  ): Promise<{ svg: string }>;
}

export interface MermaidDeps {
  load: () => Promise<MermaidLike>;
  check: (svg: string) => { ok: true } | { ok: false; reason: string };
  toUrl: (svg: string) => string;
  /** An offscreen container to draw in, and how to remove it. */
  container?: () => { element: Element; dispose: () => void };
}

export type MermaidResult =
  | { ok: true; url: string }
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

const BANNED_DIRECTIVE =
  /%%\s*\{[\s\S]*?(securityLevel|htmlLabels|secure|dompurifyConfig)[\s\S]*?\}\s*%%/i;

export function refusedDirective(source: string): boolean {
  return BANNED_DIRECTIVE.test(source);
}

let queue: Promise<unknown> = Promise.resolve();
let counter = 0;

/** Draw one diagram. Calls are serialised: mermaid keeps global state. */
export function drawMermaid(
  source: string,
  dark: boolean,
  deps: MermaidDeps,
): Promise<MermaidResult> {
  const run = async (): Promise<MermaidResult> => {
    if (!source.trim()) return { ok: false, reason: "empty" };
    if (refusedDirective(source)) {
      return { ok: false, reason: "a directive that changes security" };
    }
    let box: { element: Element; dispose: () => void } | undefined;
    try {
      const mermaid = await deps.load();
      mermaid.initialize(mermaidConfig(dark));
      box = deps.container?.();
      const id = `omni-mmd-${++counter}`;
      const { svg } = await mermaid.render(id, source, box?.element);
      if (typeof svg !== "string" || !svg)
        return { ok: false, reason: "no output" };
      const verdict = deps.check(svg);
      if (!verdict.ok) return { ok: false, reason: verdict.reason };
      return { ok: true, url: deps.toUrl(svg) };
    } catch {
      return { ok: false, reason: "mermaid could not draw it" };
    } finally {
      box?.dispose();
    }
  };
  const next = queue.then(run, run);
  queue = next.catch(() => undefined);
  return next;
}

/** The browser's offscreen container: inert, hidden, removed after. */
export function offscreenContainer(): {
  element: Element;
  dispose: () => void;
} {
  const el = document.createElement("div");
  el.setAttribute("aria-hidden", "true");
  el.setAttribute("inert", "");
  el.style.cssText =
    "position:fixed;left:-20000px;top:0;width:1600px;visibility:hidden;pointer-events:none;contain:strict;height:1px;overflow:hidden";
  document.body.appendChild(el);
  return {
    element: el,
    dispose: () => {
      el.remove();
    },
  };
}
