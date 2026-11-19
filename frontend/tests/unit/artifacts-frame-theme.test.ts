import { afterEach, describe, expect, it, vi } from "vitest";

import { readThemeVars, THEME_TOKENS } from "@/core/artifacts/frame-host";

/**
 * The viewer's preview theme button: readThemeVars(theme) reads that
 * theme's tokens from a hidden element carrying its class, never from (and
 * never changing) <html>; with no theme it reads <html> exactly as before.
 * A minimal DOM stand-in: computed tokens depend on the element's class.
 */

const VALUES = {
  light: { "--background": "#ffffff", "--foreground": "#111111" },
  dark: { "--background": "#0b0b0c", "--foreground": "#f2f2f2" },
} as const;

interface FakeEl {
  className: string;
  style: Record<string, string>;
  attrs: Record<string, string>;
  setAttribute(k: string, v: string): void;
  remove(): void;
}

function setup(appTheme: "light" | "dark") {
  const attached: FakeEl[] = [];
  const html = { className: appTheme, classList: [appTheme] };
  const body = {
    appendChild(el: FakeEl) {
      attached.push(el);
    },
  };
  const doc = {
    documentElement: html,
    body,
    createElement: () => {
      const el: FakeEl = {
        className: "",
        style: {},
        attrs: {},
        setAttribute(k, v) {
          el.attrs[k] = v;
        },
        remove() {
          attached.splice(attached.indexOf(el), 1);
        },
      };
      return el;
    },
  };
  const read = vi.fn((el: { className: string }) => ({
    getPropertyValue: (name: string) =>
      (VALUES[el.className as "light" | "dark"] as Record<string, string>)[
        name
      ] ?? "",
  }));
  vi.stubGlobal("window", {});
  vi.stubGlobal("document", doc);
  vi.stubGlobal("getComputedStyle", read);
  return { html, attached, read };
}

afterEach(() => vi.unstubAllGlobals());

describe("readThemeVars", () => {
  it("with no theme reads <html> exactly as before", () => {
    const { html, read, attached } = setup("dark");
    expect(readThemeVars()).toEqual(VALUES.dark);
    expect(read).toHaveBeenCalledTimes(1);
    expect(read.mock.calls[0]![0]).toBe(html);
    expect(attached).toHaveLength(0);
  });

  it("with a theme reads that theme's tokens, not the app's", () => {
    const { html, read, attached } = setup("dark");
    expect(readThemeVars("light")).toEqual(VALUES.light);
    expect(read.mock.calls[0]![0]).not.toBe(html);
    expect(read.mock.calls[0]![0].className).toBe("light");
    // the probe is gone and <html> keeps the app's class
    expect(attached).toHaveLength(0);
    expect(html.className).toBe("dark");
    expect(readThemeVars("dark")).toEqual(VALUES.dark);
  });

  it("only asks for the Graphite tokens", () => {
    setup("light");
    expect(THEME_TOKENS).toContain("--background");
    expect(Object.keys(readThemeVars("dark"))).toEqual([
      "--background",
      "--foreground",
    ]);
  });
});
