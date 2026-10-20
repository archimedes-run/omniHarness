/**
 * Text below WCAG AA contrast on the rendered page (Phase 2.5 colour pass).
 * Evaluated in the browser by tests/rendering/contrast.spec.ts (and the other
 * rendering specs that import it).
 *
 * The probe judges the EFFECTIVE colours, the ones actually painted:
 *
 * - The background is the stack at the text's centre (elementsFromPoint),
 *   from the text's own element down to the first layer painted fully opaque,
 *   over the page's own background. Walking the element's ancestors alone
 *   gets an absolutely positioned element wrong (a badge over its menu
 *   button). elementsFromPoint skips pointer-events:none, so the element is
 *   made hit-testable for the measurement.
 * - CSS opacity is applied as the browser applies it: an element with
 *   opacity < 1 is a group, its content (backgrounds and text inside it)
 *   composited on its own and then faded over what is behind it. Groups
 *   nest, so `opacity-30` anywhere above the text, or on a
 *   background-carrying ancestor, counts.
 * - Colours come from getComputedStyle and are parsed here (rgb/rgba,
 *   color(srgb | srgb-linear | display-p3 | xyz…), oklab, oklch, lab, lch),
 *   alpha included, so `text-foreground/30` (a color-mix the browser resolves
 *   to a colour with alpha) counts. A computed colour in a form this cannot
 *   parse throws: the run fails loudly rather than skipping the text.
 *
 * Finite animations and transitions are finished first, so a fade-in is
 * judged at its end state rather than at whatever frame the probe lands on.
 * Each element is scrolled into view first, because workspace pages scroll
 * inside a container, not the window.
 *
 * Skipped: text over a gradient or image (cannot be judged this way),
 * inactive controls (WCAG 1.4.3 exempts them), hidden or decorative text, and
 * text faded below 10% opacity (a cross-fading layer that is not seen).
 *
 * The probe is serialised into the page, so `probe` and `contrastMath` are
 * self-contained (no imports, no closures over module scope); `contrastMath`
 * is unit-tested on its own (tests/unit/contrast-math.test.ts).
 */
export interface LowContrast {
  text: string;
  ratio: number;
  need: number;
  color: string;
  cls: string;
}

/** Straight (not premultiplied) sRGB, channels 0..255, alpha 0..1. */
export type RGBA = [number, number, number, number];

/** One painted layer, and the opacity groups it is inside (outermost first). */
export interface Layer {
  color: RGBA;
  groups: { key: unknown; opacity: number }[];
}

export function contrastMath() {
  type C = [number, number, number, number];
  type V3 = [number, number, number];
  type M3 = [V3, V3, V3];
  const mul = (m: M3, v: V3): V3 =>
    m.map((r) => r[0] * v[0] + r[1] * v[1] + r[2] * v[2]) as V3;
  const XYZ65_TO_LSRGB: M3 = [
    [3.2409699419045226, -1.537383177570094, -0.4986107602930034],
    [-0.9692436362808796, 1.8759675015077202, 0.04155505740717559],
    [0.05563007969699366, -0.20397695888897652, 1.0569715142428786],
  ];
  const D50_TO_D65: M3 = [
    [0.955473421488075, -0.02309845494876471, 0.06325924320057072],
    [-0.0283697093338637, 1.0099953980813041, 0.021041441191917323],
    [0.012314014864481998, -0.020507649298898964, 1.330365926242124],
  ];
  const LP3_TO_XYZ65: M3 = [
    [0.4865709486482162, 0.26566769316909306, 0.1982172852343625],
    [0.2289745640697488, 0.6917385218365064, 0.079286914093745],
    [0, 0.04511338185890264, 1.043944368900976],
  ];
  const decode = (c: number) => {
    const a = Math.abs(c);
    return (
      Math.sign(c) * (a <= 0.04045 ? a / 12.92 : ((a + 0.055) / 1.055) ** 2.4)
    );
  };
  const encode = (c: number) => {
    const a = Math.abs(c);
    return (
      Math.sign(c) *
      (a <= 0.0031308 ? a * 12.92 : 1.055 * a ** (1 / 2.4) - 0.055)
    );
  };
  const clip = (v: number) => Math.min(1, Math.max(0, v));
  /** Linear-light sRGB to 0..255 gamma-encoded channels, gamut-clipped. */
  const fromLinear = (l: V3, alpha: number): C => [
    clip(encode(l[0])) * 255,
    clip(encode(l[1])) * 255,
    clip(encode(l[2])) * 255,
    clip(alpha),
  ];
  const oklabToLinear = (L: number, a: number, b: number): V3 => {
    const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3;
    const m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3;
    const s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3;
    return [
      4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
      -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
      -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s,
    ];
  };
  const labToLinear = (L: number, a: number, b: number): V3 => {
    const k = 24389 / 27;
    const e = 216 / 24389;
    const fy = (L + 16) / 116;
    const fx = a / 500 + fy;
    const fz = fy - b / 200;
    const f = (t: number) => (t ** 3 > e ? t ** 3 : (116 * t - 16) / k);
    const xyz50: V3 = [
      (f(fx) * 0.3457) / 0.3585,
      L > k * e ? fy ** 3 : L / k,
      (f(fz) * (1 - 0.3457 - 0.3585)) / 0.3585,
    ];
    return mul(XYZ65_TO_LSRGB, mul(D50_TO_D65, xyz50));
  };

  /**
   * A computed CSS colour (what getComputedStyle returns) as straight sRGB.
   * Throws on anything it cannot parse: never a silent skip.
   */
  const parse = (css: string): C => {
    const fail = () =>
      new Error(`contrast probe: cannot parse computed colour "${css}"`);
    const s = css.trim().toLowerCase();
    if (s === "transparent") return [0, 0, 0, 0];
    const m = /^([a-z-]+)\(([^()]*)\)$/.exec(s);
    if (!m) throw fail();
    const fn = m[1]!;
    const [main, alphaPart, extra] = m[2]!.split("/");
    if (extra !== undefined) throw fail();
    const parts = main!
      .replace(/,/g, " ")
      .trim()
      .split(/\s+/)
      .filter((p) => p !== "");
    const space = fn === "color" ? parts.shift() : undefined;
    // Legacy comma syntax, rgba(r, g, b, a), carries alpha as a 4th part.
    let alphaTok = alphaPart?.trim();
    if (alphaTok === undefined && parts.length === 4) alphaTok = parts.pop();
    if (parts.length !== 3) throw fail();
    const num = (t: string | undefined, pct = 1): number => {
      if (t === undefined || t === "none") return 0;
      const v = Number(t.replace(/(%|deg)$/, ""));
      if (!Number.isFinite(v)) throw fail();
      return t.endsWith("%") ? (v / 100) * pct : v;
    };
    const alpha = alphaTok === undefined ? 1 : clip(num(alphaTok, 1));
    const [p0, p1, p2] = parts as [string, string, string];
    const polar = (c: number, h: string): [number, number] => {
      const rad = (num(h) * Math.PI) / 180;
      return [c * Math.cos(rad), c * Math.sin(rad)];
    };
    switch (fn) {
      case "rgb":
      case "rgba":
        return [
          clip(num(p0, 255) / 255) * 255,
          clip(num(p1, 255) / 255) * 255,
          clip(num(p2, 255) / 255) * 255,
          alpha,
        ];
      case "oklab":
        return fromLinear(
          oklabToLinear(num(p0), num(p1, 0.4), num(p2, 0.4)),
          alpha,
        );
      case "oklch":
        return fromLinear(
          oklabToLinear(num(p0), ...polar(num(p1, 0.4), p2)),
          alpha,
        );
      case "lab":
        return fromLinear(
          labToLinear(num(p0, 100), num(p1, 125), num(p2, 125)),
          alpha,
        );
      case "lch":
        return fromLinear(
          labToLinear(num(p0, 100), ...polar(num(p1, 150), p2)),
          alpha,
        );
      case "color": {
        const v: V3 = [num(p0, 1), num(p1, 1), num(p2, 1)];
        const lin = v.map(decode) as V3;
        if (space === "srgb") return fromLinear(lin, alpha);
        if (space === "srgb-linear") return fromLinear(v, alpha);
        if (space === "display-p3")
          return fromLinear(mul(XYZ65_TO_LSRGB, mul(LP3_TO_XYZ65, lin)), alpha);
        if (space === "xyz" || space === "xyz-d65")
          return fromLinear(mul(XYZ65_TO_LSRGB, v), alpha);
        if (space === "xyz-d50")
          return fromLinear(mul(XYZ65_TO_LSRGB, mul(D50_TO_D65, v)), alpha);
        throw fail();
      }
    }
    throw fail();
  };

  /** `top` painted over `under` (source-over, straight alpha). */
  const over = (top: C, under: C): C => {
    const a = top[3] + under[3] * (1 - top[3]);
    if (a <= 0) return [0, 0, 0, 0];
    const ch = (i: 0 | 1 | 2) =>
      (top[i] * top[3] + under[i] * under[3] * (1 - top[3])) / a;
    return [ch(0), ch(1), ch(2), a];
  };

  /**
   * The colour from painting `layers` bottom to top, honouring CSS opacity
   * groups: consecutive layers inside the same group are composited on their
   * own (from transparent), that result faded by the group's opacity and
   * painted over what is below it, recursively for nested groups.
   */
  const composite = (layers: Layer[]): C => {
    const run = (items: Layer[], depth: number): C => {
      let out: C = [0, 0, 0, 0];
      let i = 0;
      while (i < items.length) {
        const g = items[i]!.groups[depth];
        if (!g) {
          out = over(items[i]!.color, out);
          i++;
          continue;
        }
        let j = i;
        while (j < items.length && items[j]!.groups[depth]?.key === g.key) j++;
        const inner = run(items.slice(i, j), depth + 1);
        out = over([inner[0], inner[1], inner[2], inner[3] * g.opacity], out);
        i = j;
      }
      return out;
    };
    return run(layers, 0);
  };

  const luminance = ([r, g, b]: C) => {
    const [lr, lg, lb] = [r, g, b].map((v) => {
      const c = v / 255;
      return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
    }) as V3;
    return 0.2126 * lr + 0.7152 * lg + 0.0722 * lb;
  };
  /** WCAG contrast ratio of two opaque colours. */
  const ratio = (a: C, b: C) => {
    const [hi, lo] = [luminance(a), luminance(b)].sort((p, q) => q - p) as [
      number,
      number,
    ];
    return (hi + 0.05) / (lo + 0.05);
  };
  return { parse, over, composite, ratio };
}

function probe(math: typeof contrastMath): LowContrast[] {
  const { parse, composite, ratio } = math();
  type Group = Layer["groups"][number];

  /** `el` and its ancestors with opacity < 1, outermost first. */
  const groupsOf = (el: Element): Group[] => {
    const out: Group[] = [];
    for (let n: Element | null = el; n; n = n.parentElement) {
      const o = Number(getComputedStyle(n).opacity);
      if (o < 1) out.unshift({ key: n, opacity: o });
    }
    return out;
  };

  const pageLayer = (): Layer => {
    for (const n of [document.body, document.documentElement]) {
      const c = parse(getComputedStyle(n).backgroundColor);
      if (c[3] >= 1) return { color: c, groups: [] };
    }
    return { color: [255, 255, 255, 1], groups: [] };
  };

  /** Painted layers under the text, bottom to top; null over an image. */
  const layersUnder = (el: HTMLElement): Layer[] | null => {
    const r = el.getBoundingClientRect();
    const x = Math.min(Math.max(r.left + r.width / 2, 0), innerWidth - 1);
    const y = Math.min(Math.max(r.top + r.height / 2, 0), innerHeight - 1);
    const previous = el.style.pointerEvents;
    el.style.pointerEvents = "auto";
    let stack = document.elementsFromPoint(x, y);
    el.style.pointerEvents = previous;
    // The text paints over its own element's background and what is under
    // it, not under its descendants' backgrounds.
    const at = stack.indexOf(el);
    if (at > 0) stack = stack.slice(at);
    const layers: Layer[] = [];
    for (const n of stack) {
      const s = getComputedStyle(n);
      if (s.backgroundImage && s.backgroundImage !== "none") return null;
      const color = parse(s.backgroundColor);
      if (color[3] <= 0) continue;
      const groups = groupsOf(n);
      layers.push({ color, groups });
      // Opaque and not faded by any group: nothing below it shows through.
      if (color[3] >= 1 && groups.length === 0) break;
    }
    return [pageLayer(), ...layers.reverse()];
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

  // Judge the settled page, not a frame of a fade: finite animations and
  // transitions (a step fading in, a panel sliding open) are run to their end
  // state first. Endless ones (a blinking caret) are judged as they are.
  for (const a of document.getAnimations()) {
    const end = a.effect?.getComputedTiming().endTime;
    if (typeof end === "number" && Number.isFinite(end)) a.finish();
  }

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
    const groups = groupsOf(el);
    // Text in a layer faded below 10% (a demo cross-fading between views)
    // is not seen, so it is not judged. Anything more visible is judged at
    // the opacity it is painted with.
    if (groups.reduce((o, g) => o * g.opacity, 1) < 0.1) continue;
    if (
      el.closest(
        "[aria-hidden=true], .sr-only, svg, :disabled, [aria-disabled=true]",
      )
    )
      continue;
    const under = layersUnder(el);
    if (!under) continue;
    const bg = composite(under);
    const fg = composite([...under, { color: parse(s.color), groups }]);
    const size = parseFloat(s.fontSize);
    const bold = Number(s.fontWeight) >= 700;
    const need = size >= 24 || (bold && size >= 18.66) ? 3 : 4.5;
    const got = ratio(fg, bg);
    if (got < need) {
      const faded = groups.length
        ? ` at opacity ${groups.map((g) => g.opacity).join("×")}`
        : "";
      found.push({
        text: node.textContent.trim().slice(0, 50),
        ratio: Math.round(got * 100) / 100,
        need,
        color: s.color + faded,
        cls: typeof el.className === "string" ? el.className.slice(0, 100) : "",
      });
    }
  }
  return found;
}

/**
 * The probe as one self-contained function for page.evaluate. Playwright
 * sends a function to the page as its source text, so the maths is spliced
 * in as source rather than closed over.
 */
// eslint-disable-next-line @typescript-eslint/no-implied-eval -- test-only: our own two functions' source, joined so the page gets one function
export const lowContrastText = new Function(
  `return (${probe.toString()})(${contrastMath.toString()});`,
) as () => LowContrast[];
