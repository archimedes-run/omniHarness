import { describe, expect, it } from "vitest";

import { checkSvgText } from "@/core/artifacts/svg-allowlist";

import { parseXml } from "./helpers/mini-xml";

/**
 * Spec 012 FR-014/FR-015: the frontend port of the gateway's SVG allowlist,
 * which every mermaid drawing must pass before it becomes an <img>.
 */
const NS = 'xmlns="http://www.w3.org/2000/svg"';
const XL = 'xmlns:xlink="http://www.w3.org/1999/xlink"';
const check = (svg: string) => checkSvgText(svg, parseXml);

describe("checkSvgText", () => {
  it("passes plain shapes, text, gradients, markers and url(#id)", () => {
    expect(
      check(
        `<svg ${NS} ${XL} viewBox="0 0 10 10" role="img" aria-label="x" data-id="1">` +
          `<defs><marker id="m"><path d="M0 0"/></marker><linearGradient id="g"><stop offset="0"/></linearGradient></defs>` +
          `<style>.a{fill:url(#g)}</style><g class="a"><rect width="1" height="1" fill="url(#g)" marker-end="url(#m)"/>` +
          `<text x="1" y="1"><tspan>Hi</tspan></text><use xlink:href="#m"/></g></svg>`,
      ),
    ).toEqual({ ok: true });
  });

  it("passes the two inert attributes mermaid writes: name (sequence) and transform-origin (gantt)", () => {
    expect(
      check(
        `<svg ${NS}><g name="actor"><rect transform-origin="0 0"/></g></svg>`,
      ),
    ).toEqual({ ok: true });
  });

  it.each([
    ["script", `<svg ${NS}><script>x()</script></svg>`],
    ["foreignObject", `<svg ${NS}><foreignObject/></svg>`],
    ["a link element", `<svg ${NS}><a href="#x"><text>x</text></a></svg>`],
    ["switch", `<svg ${NS}><switch/></svg>`],
    ["an event attribute", `<svg ${NS} onload="x()"/>`],
    [
      "an outside href",
      `<svg ${NS} ${XL}><use xlink:href="https://evil.example/a.svg#x"/></svg>`,
    ],
    [
      "an outside image",
      `<svg ${NS}><image href="https://evil.example/p.png"/></svg>`,
    ],
    [
      "url() to elsewhere in an attribute",
      `<svg ${NS}><rect fill="url(https://evil.example/x)"/></svg>`,
    ],
    [
      "url() to elsewhere in style",
      `<svg ${NS}><style>a{background:url(/api/logout)}</style></svg>`,
    ],
    ["@import", `<svg ${NS}><style>@import "x.css";</style></svg>`],
    [
      "a CSS escape",
      `<svg ${NS}><style>a{background:u\\72l(/x)}</style></svg>`,
    ],
    [
      "javascript: split by whitespace",
      `<svg ${NS}><rect style="x:java\tscript:1"/></svg>`,
    ],
    ["an unknown attribute", `<svg ${NS}><rect formaction="x"/></svg>`],
    [
      "an element outside the SVG namespace",
      `<svg ${NS}><img xmlns="http://www.w3.org/1999/xhtml"/></svg>`,
    ],
    ["a non-svg root", `<html ${NS}/>`],
    ["a DOCTYPE", `<!DOCTYPE svg><svg ${NS}/>`],
    ["an xml-stylesheet", `<?xml-stylesheet href="x.css"?><svg ${NS}/>`],
    ["malformed XML", `<svg ${NS}><g></svg>`],
  ])("refuses %s", (_name, svg) => {
    expect(check(svg).ok).toBe(false);
  });

  it("an <image> may embed only a base64 PNG, JPEG, GIF or WebP", () => {
    expect(
      check(`<svg ${NS}><image href="data:image/png;base64,AAAA"/></svg>`),
    ).toEqual({ ok: true });
    expect(
      check(`<svg ${NS}><image href="data:image/svg+xml;base64,AAAA"/></svg>`)
        .ok,
    ).toBe(false);
  });
});
