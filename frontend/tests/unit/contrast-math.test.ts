import { describe, expect, it } from "vitest";

import {
  contrastMath,
  type Layer,
  type RGBA,
} from "../rendering/contrast-probe";

/**
 * The compositing maths behind the rendering contrast probe
 * (tests/rendering/contrast-probe.ts). The probe judges what is painted, so
 * CSS opacity (multiplied through every ancestor), text alpha and
 * semi-transparent backgrounds all change the colours it compares.
 *
 * The computed-colour strings below are what headless Chromium's
 * getComputedStyle returns for the CSS shown beside them.
 */
const { parse, over, composite, ratio } = contrastMath();

const WHITE: RGBA = [255, 255, 255, 1];
const BLACK: RGBA = [0, 0, 0, 1];
const near = (got: RGBA, want: RGBA, tol = 1.5) => {
  for (let i = 0; i < 3; i++)
    expect(Math.abs(got[i]! - want[i]!)).toBeLessThanOrEqual(tol);
  expect(got[3]).toBeCloseTo(want[3], 3);
};
const layer = (color: RGBA, ...groups: [unknown, number][]): Layer => ({
  color,
  groups: groups.map(([key, opacity]) => ({ key, opacity })),
});

describe("parse: computed colours", () => {
  it("reads rgb() and legacy rgba()", () => {
    near(parse("rgb(23, 24, 27)"), [23, 24, 27, 1], 0);
    near(parse("rgba(10, 20, 30, 0.5)"), [10, 20, 30, 0.5], 0);
    near(parse("rgb(10 20 30 / 25%)"), [10, 20, 30, 0.25], 0);
    near(parse("transparent"), [0, 0, 0, 0], 0);
    near(parse("rgba(0, 0, 0, 0)"), [0, 0, 0, 0], 0);
  });

  it("reads oklch, oklab, lab and lch (pure red in each)", () => {
    near(parse("oklch(0.628 0.2577 29.23)"), [255, 0, 0, 1], 2);
    near(parse("oklab(0.628 0.2249 0.1258)"), [255, 0, 0, 1], 2);
    near(parse("lab(54.29 80.82 69.89)"), [255, 0, 0, 1], 2);
    near(parse("lch(54.29 106.84 40.85)"), [255, 0, 0, 1], 2);
    near(parse("oklch(1 0 0)"), WHITE, 1);
    near(parse("oklch(0 0 none)"), BLACK, 1);
  });

  it("reads color(srgb …), color(srgb-linear …) and display-p3", () => {
    // color-mix(in srgb, red 50%, blue)
    near(parse("color(srgb 0.5 0 0.5)"), [127.5, 0, 127.5, 1], 0.1);
    near(parse("color(srgb-linear 1 1 1 / 0.5)"), [255, 255, 255, 0.5], 0.1);
    // display-p3 red is outside sRGB: clipped to sRGB red.
    near(parse("color(display-p3 1 0 0)"), [255, 0, 0, 1], 1);
  });

  it("reads colour-mix results, alpha included", () => {
    // color-mix(in oklab, rgb(23 24 27) 30%, transparent): text-foreground/30
    near(
      parse("oklab(0.209237 0.000128426 -0.00610217 / 0.3)"),
      [23, 24, 27, 0.3],
      1,
    );
    // color-mix(in oklch, oklch(0.5 0.1 250) 40%, transparent)
    expect(parse("oklch(0.5 0.1 250 / 0.4)")[3]).toBeCloseTo(0.4, 5);
    // color-mix(in srgb, oklch(0.7 0.1 200) 50%, white)
    near(
      parse("color(srgb 0.625807 0.847141 0.858555)"),
      [159.6, 216, 218.9, 1],
      0.5,
    );
  });

  it("fails loudly on a colour it cannot parse, never skips it", () => {
    for (const css of [
      "color(rec2020 1 0 0)",
      "hwb(0 0% 0%)",
      "currentcolor",
      "rgb(1 2)",
      "rgb(a b c)",
      "",
    ])
      expect(() => parse(css), css).toThrow(/cannot parse computed colour/);
  });
});

describe("composite: what is painted", () => {
  it("text alpha over an opaque background", () => {
    const fg = over([0, 0, 0, 0.5], WHITE);
    near(fg, [127.5, 127.5, 127.5, 1], 0.01);
  });

  it("alpha text over an alpha background over the page", () => {
    // A 50% black panel over white is mid grey; 50% white text over that
    // is three-quarter grey.
    const bg = composite([layer(WHITE), layer([0, 0, 0, 0.5])]);
    near(bg, [127.5, 127.5, 127.5, 1], 0.01);
    const fg = composite([
      layer(WHITE),
      layer([0, 0, 0, 0.5]),
      layer([255, 255, 255, 0.5]),
    ]);
    near(fg, [191.25, 191.25, 191.25, 1], 0.01);
  });

  it("multiplies opacity through every ancestor of the text", () => {
    // Black text in two nested opacity-50 groups, over white: 25% black.
    const fg = composite([
      layer(WHITE),
      layer(BLACK, ["outer", 0.5], ["inner", 0.5]),
    ]);
    near(fg, [191.25, 191.25, 191.25, 1], 0.01);
    expect(ratio(fg, WHITE)).toBeLessThan(3);
    // opacity-30 on near-black text over white: far under AA.
    const faded = composite([layer(WHITE), layer([23, 24, 27, 1], ["p", 0.3])]);
    expect(ratio(faded, WHITE)).toBeLessThan(4.5);
    expect(
      ratio(composite([layer(WHITE), layer([23, 24, 27, 1])]), WHITE),
    ).toBeGreaterThan(15);
  });

  it("an opacity group fades its own background together with its text", () => {
    // A black chip with white text, the chip at opacity 0.5, on white: the
    // chip paints mid grey and the text stays white, as the browser does it
    // (the group is flattened, then faded once).
    const under = [layer(WHITE), layer(BLACK, ["chip", 0.5])];
    const bg = composite(under);
    const fg = composite([...under, layer(WHITE, ["chip", 0.5])]);
    near(bg, [127.5, 127.5, 127.5, 1], 0.01);
    near(fg, WHITE, 0.01);
  });

  it("opacity on a background-carrying ancestor lets the page show through", () => {
    // A black card at opacity 0.3 on a white page is light grey, so white
    // text on it fails even though white on black would pass.
    const under = [layer(WHITE), layer(BLACK, ["card", 0.3])];
    const bg = composite(under);
    const fg = composite([...under, layer(WHITE, ["card", 0.3])]);
    expect(ratio(fg, bg)).toBeCloseTo(2.11, 2);
    expect(ratio(WHITE, BLACK)).toBeCloseTo(21, 5);
  });

  it("different groups at the same depth are composited separately", () => {
    const fg = composite([
      layer(WHITE),
      layer(BLACK, ["a", 0.5]),
      layer(BLACK, ["b", 0.5]),
    ]);
    near(fg, [63.75, 63.75, 63.75, 1], 0.01);
  });
});
