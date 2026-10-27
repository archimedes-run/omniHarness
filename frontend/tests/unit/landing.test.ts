import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import LandingPage from "@/app/page";
import { NAV_LINKS, SECTION_IDS } from "@/components/landing/links";

/**
 * The landing page ("B · Product-first"): its sections render in order, every
 * in-page anchor the header and the page link to resolves to a rendered id,
 * no H2 is repeated, and nothing on it animates forever. Colours are checked
 * site-wide by colour-tokens.test.ts and measured in both themes by
 * tests/rendering/contrast.spec.ts.
 */
const html = renderToStaticMarkup(createElement(LandingPage));

const ids = new Set([...html.matchAll(/\sid="([^"]+)"/g)].map((m) => m[1]!));
const hrefs = [...html.matchAll(/\shref="([^"]+)"/g)].map((m) => m[1]!);
const text = (s: string) =>
  s
    .replace(/<[^>]+>/g, "")
    .replace(/&#x27;|&apos;/g, "'")
    .replace(/&amp;/g, "&")
    .trim();
const headings = (level: number) =>
  [...html.matchAll(new RegExp(`<h${level}[^>]*>(.*?)</h${level}>`, "gs"))].map(
    (m) => text(m[1]!),
  );

/** The Asks first tier card: from its heading to the end of its <li>. */
function asksFirst(markup: string): string {
  const at = markup.indexOf(">Asks first<");
  if (at < 0) return "";
  const start = markup.lastIndexOf("<li", at);
  return markup.slice(start, markup.indexOf("</li>", at));
}

describe("landing page", () => {
  it("POSITIVE CONTROL: the helpers see ids, hrefs and headings", () => {
    expect(ids.size).toBeGreaterThan(3);
    expect(hrefs.length).toBeGreaterThan(5);
    expect(headings(1)).toHaveLength(1);
  });

  it("has the hero, then the sections in order", () => {
    expect(headings(1)[0]).toBe(
      "A team of AI agentsthat works for you, at home.",
    );
    expect(headings(2)).toEqual([
      "A day with OmniHarness",
      "What it does",
      "Safe by design",
      "Runs on your machine",
    ]);
    const order = Object.values(SECTION_IDS).map((id) =>
      html.indexOf(` id="${id}"`),
    );
    // day, then product, then safety
    expect(order.every((i) => i > 0)).toBe(true);
    const [product, day, safety] = order;
    expect(day).toBeLessThan(product!);
    expect(product).toBeLessThan(safety!);
  });

  it("repeats no H2", () => {
    const h2 = headings(2);
    expect(new Set(h2).size).toBe(h2.length);
  });

  it("every header anchor is /#id and resolves to a rendered section", () => {
    const anchors = NAV_LINKS.map((l) => l.href).filter((h) => h.includes("#"));
    expect(anchors).toHaveLength(3);
    for (const href of anchors) {
      expect(href, "absolute, so it works from the blog and docs").toMatch(
        /^\/#/,
      );
      expect(ids, `${href} has no target`).toContain(href.slice(2));
    }
  });

  it("every in-page link on the page resolves to a rendered id", () => {
    const local = hrefs.filter((h) => h.startsWith("#") || h.startsWith("/#"));
    expect(local.length).toBeGreaterThan(0);
    for (const h of local) expect(ids).toContain(h.split("#")[1]);
  });

  it("the calls to action go to the workspace, GitHub and the docs", () => {
    expect(hrefs.filter((h) => h === "/workspace")).toHaveLength(2);
    expect(hrefs).toContain("https://github.com/archimedes-run/omniHarness");
    expect(hrefs).toContain("/en/docs");
  });

  it("has a menu button for small screens", () => {
    expect(html).toMatch(/aria-label="Open menu"/);
    expect(html).toMatch(/aria-controls="landing-mobile-menu"/);
  });

  it("follows the theme: a token background, no fixed white glow or fade", () => {
    expect(html).toMatch(/class="bg-background [^"]*min-h-screen/);
    expect(html).not.toMatch(/radial-gradient|to white|rgba\(255/);
  });

  it("claims nothing that is not shipped", () => {
    expect(html).not.toMatch(/opencode/i);
    // MCP Build isn't merged yet.
    expect(html).not.toMatch(/MCP Build/i);
  });

  it("never offers Apply all for the asks-first tier", () => {
    const tier3 = asksFirst(html);
    expect(tier3, "the Asks first tier is not on the page").toMatch(
      /Asks first/,
    );
    expect(tier3).not.toMatch(/apply all/i);
  });

  it("keeps the phone menu in the DOM, hidden, so aria-controls resolves", () => {
    expect(html).toMatch(/<div id="landing-mobile-menu" hidden=""/);
    const nav = html.slice(
      html.indexOf('<nav aria-label="Main"'),
      html.indexOf("</nav>"),
    );
    expect(nav, "the menu sits inside the nav landmark").toContain(
      'id="landing-mobile-menu"',
    );
  });

  it("gives the timeline machine-readable times", () => {
    const times = [...html.matchAll(/<time dateTime="([^"]*)"/g)].map(
      (m) => m[1]!,
    );
    expect(times).toHaveLength(5);
    for (const t of times) expect(t).toMatch(/^([01]\d|2[0-3]):[0-5]\d$/);
  });
});

describe("landing source", () => {
  const dir = join(__dirname, "..", "..", "src", "components", "landing");
  const walk = (d: string): string[] =>
    readdirSync(d).flatMap((n) => {
      const p = join(d, n);
      return statSync(p).isDirectory() ? walk(p) : [p];
    });
  const sources = walk(dir).map((f) => readFileSync(f, "utf8"));

  it("POSITIVE CONTROL: the walk reads the landing files", () => {
    expect(sources.length).toBeGreaterThan(5);
  });

  it("runs no animation loop, and animates only when motion is allowed", () => {
    for (const s of sources) {
      expect(s).not.toMatch(/requestAnimationFrame|setInterval/);
      expect(s).not.toMatch(/\banimate-(?!none)/);
    }
  });
});
