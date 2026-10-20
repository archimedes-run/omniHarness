/**
 * Text below WCAG AA contrast on the rendered page (Phase 2.5 colour pass).
 * Evaluated in the browser by tests/rendering/contrast.spec.ts, so it must be
 * self-contained: no imports, no closures over module scope.
 *
 * The background is what is actually painted under the text: the stack at its
 * centre (elementsFromPoint), composited top-down until opaque, over the page's
 * own background. Walking the element's ancestors alone gets an absolutely
 * positioned element wrong (a badge over its menu button). elementsFromPoint
 * skips pointer-events:none, so the element is made hit-testable for the
 * measurement. Each element is scrolled into view first, because workspace
 * pages scroll inside a container, not the window. Colours go through a
 * canvas, so any CSS colour (oklch, lab, color-mix) parses.
 *
 * Skipped: text over a gradient or image (cannot be judged this way), inactive
 * controls (WCAG 1.4.3 exempts them), and hidden or decorative text.
 */
export interface LowContrast {
  text: string;
  ratio: number;
  need: number;
  color: string;
  cls: string;
}

export function lowContrastText(): LowContrast[] {
  type RGBA = [number, number, number, number];
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 1;
  const ctx = canvas.getContext("2d", { willReadFrequently: true })!;

  const rgba = (css: string): RGBA => {
    ctx.clearRect(0, 0, 1, 1);
    ctx.fillStyle = "#000";
    ctx.fillStyle = css;
    ctx.fillRect(0, 0, 1, 1);
    const d = ctx.getImageData(0, 0, 1, 1).data;
    return [d[0]!, d[1]!, d[2]!, d[3]! / 255];
  };
  const over = (top: RGBA, under: RGBA): RGBA => {
    const a = top[3];
    return [
      top[0] * a + under[0] * (1 - a),
      top[1] * a + under[1] * (1 - a),
      top[2] * a + under[2] * (1 - a),
      1,
    ];
  };
  const luminance = ([r, g, b]: RGBA) => {
    const [lr, lg, lb] = [r, g, b].map((v) => {
      const c = v / 255;
      return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
    }) as [number, number, number];
    return 0.2126 * lr + 0.7152 * lg + 0.0722 * lb;
  };
  const ratio = (a: RGBA, b: RGBA) => {
    const [hi, lo] = [luminance(a), luminance(b)].sort((p, q) => q - p) as [
      number,
      number,
    ];
    return (hi + 0.05) / (lo + 0.05);
  };

  const page = (): RGBA => {
    for (const n of [document.body, document.documentElement]) {
      const c = rgba(getComputedStyle(n).backgroundColor);
      if (c[3] >= 1) return c;
    }
    return [255, 255, 255, 1];
  };

  const background = (el: HTMLElement): RGBA | null => {
    const r = el.getBoundingClientRect();
    const x = Math.min(Math.max(r.left + r.width / 2, 0), innerWidth - 1);
    const y = Math.min(Math.max(r.top + r.height / 2, 0), innerHeight - 1);
    const previous = el.style.pointerEvents;
    el.style.pointerEvents = "auto";
    const stack = document.elementsFromPoint(x, y);
    el.style.pointerEvents = previous;
    const layers: RGBA[] = [];
    for (const n of stack) {
      const s = getComputedStyle(n);
      if (s.backgroundImage && s.backgroundImage !== "none") return null;
      const c = rgba(s.backgroundColor);
      if (c[3] > 0) layers.push(c);
      if (c[3] >= 1) break;
    }
    let out = page();
    for (const layer of layers.reverse()) out = over(layer, out);
    return out;
  };

  const covered = (el: HTMLElement): boolean => {
    const r = el.getBoundingClientRect();
    const x = r.left + r.width / 2;
    const y = r.top + r.height / 2;
    if (x < 0 || y < 0 || x >= innerWidth || y >= innerHeight) return false;
    const previous = el.style.pointerEvents;
    el.style.pointerEvents = "auto";
    const top = document.elementFromPoint(x, y);
    el.style.pointerEvents = previous;
    return top != null && !el.contains(top) && !top.contains(el);
  };

  const found: LowContrast[] = [];
  const seen = new Set<Element>();
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const node = walker.currentNode;
    const el = node.parentElement;
    if (!el || seen.has(el) || !node.textContent?.trim()) continue;
    seen.add(el);
    let r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    if (r.width === 0 || r.height === 0) continue;
    if (r.top < 0 || r.bottom > innerHeight) {
      el.scrollIntoView({ block: "center", behavior: "instant" });
      r = el.getBoundingClientRect();
      if (r.top < 0 || r.bottom > innerHeight) continue;
    }
    // Covered at its centre by something else (a docked chat bar over the
    // end of a nested scroller): scroll it to the middle of its own
    // scroller; text still covered is not seen, so it is not judged.
    if (covered(el)) {
      el.scrollIntoView({ block: "center", behavior: "instant" });
      if (covered(el)) continue;
    }
    if (s.visibility === "hidden") continue;
    // Opacity multiplies down the tree: text in a faded-out layer (a demo
    // cross-fading between views) is not seen, so it is not judged.
    let opacity = 1;
    for (let n: Element | null = el; n; n = n.parentElement) {
      opacity *= Number(getComputedStyle(n).opacity);
    }
    if (opacity < 0.1) continue;
    if (
      el.closest(
        "[aria-hidden=true], .sr-only, svg, :disabled, [aria-disabled=true]",
      )
    )
      continue;
    const bg = background(el);
    if (!bg) continue;
    const fg = over(rgba(s.color), bg);
    const size = parseFloat(s.fontSize);
    const bold = Number(s.fontWeight) >= 700;
    const need = size >= 24 || (bold && size >= 18.66) ? 3 : 4.5;
    const got = ratio(fg, bg);
    if (got < need) {
      found.push({
        text: node.textContent.trim().slice(0, 50),
        ratio: Math.round(got * 100) / 100,
        need,
        color: s.color,
        cls: typeof el.className === "string" ? el.className.slice(0, 100) : "",
      });
    }
  }
  return found;
}
