/**
 * The dark theme must actually differ from the light one.
 *
 * WHAT THIS CATCHES. `.dark` once defined 31 tokens of which 24 were
 * byte-identical to `:root` — including `--background` (white in both),
 * `--foreground`, `--card` and `--primary`. Toggling the theme set
 * `class="dark"` on `<html>` and reassigned every variable to the value it
 * already had, so nothing visible changed except the chart palette.
 *
 * The toggle was never broken. There was no dark theme to switch to.
 *
 * That is the natural result of scaffolding a theme block by copying the light
 * one and meaning to fill it in, and it is invisible in review: the block is
 * present, the token names are all there, and the diff looks complete.
 *
 * A CSS parse, not a browser. The assertion that would REALLY prove dark mode
 * works is a rendering one — toggle, read the computed background — and that
 * needs Playwright, which cannot install in this environment. See
 * docs/FRONTEND_TESTING_GAP.md. This is the cheap check that covers the
 * specific failure we actually hit.
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const CSS = readFileSync(
  join(__dirname, "..", "..", "src", "styles", "globals.css"),
  "utf8",
);

function tokens(selector: string): Map<string, string> {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  // The light block is `:root,\n.light {`: the selector may be followed by
  // more selectors before its brace.
  const match = new RegExp(
    `^${escaped}(?:,\\s*[.\\w-]+)*\\s*\\{([\\s\\S]*?)\\n\\}`,
    "m",
  ).exec(CSS);
  if (!match) throw new Error(`no ${selector} block in globals.css`);
  const out = new Map<string, string>();
  for (const [, name, value] of (match[1] ?? "").matchAll(
    /(--[\w-]+)\s*:\s*([^;]+);/g,
  )) {
    if (name && value) out.set(name, value.trim());
  }
  return out;
}

/** Relative luminance (0..1) of a #rrggbb value, or lightness of oklch(). */
function lightness(value: string | undefined): number {
  const hex = /^#([0-9a-f]{6})$/i.exec(value ?? "")?.[1];
  if (hex) {
    const [r, g, b] = [0, 2, 4].map((i) => {
      const c = parseInt(hex.slice(i, i + 2), 16) / 255;
      return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * r! + 0.7152 * g! + 0.0722 * b!;
  }
  return Number(/oklch\(\s*([\d.]+)/.exec(value ?? "")?.[1] ?? NaN);
}

/** Tokens that govern what the user sees on every page. */
const GOVERNING = ["--background", "--foreground", "--card", "--primary"];

/** Tokens that are not colours and so have one value for both themes. */
const NOT_A_THEME_TOKEN: Record<string, string> = {
  "--radius":
    "geometry, not colour — corner radius does not change with the theme",
};

/** Shared values that are deliberate, each with the reason. */
const INTENTIONALLY_SHARED: Record<string, string> = {};

describe("the dark theme", () => {
  const light = tokens(":root");
  const dark = tokens(".dark");

  it("defines the tokens the light theme defines", () => {
    const missing = [...light.keys()].filter(
      (t) =>
        !dark.has(t) &&
        !(t in INTENTIONALLY_SHARED) &&
        !(t in NOT_A_THEME_TOKEN),
    );
    expect(
      missing,
      `.dark omits ${missing.join(", ")}, so those fall through to the light value`,
    ).toEqual([]);
  });

  it.each(GOVERNING)("uses a different value for %s", (token) => {
    expect(dark.get(token), `${token} is missing from .dark`).toBeDefined();
    expect(
      dark.get(token),
      `${token} is identical in :root and .dark (${light.get(token)}). Toggling the theme ` +
        `reassigns it to the value it already had, so nothing changes on screen.`,
    ).not.toBe(light.get(token));
  });

  it("is dark — the background is darker than the foreground", () => {
    expect(lightness(dark.get("--background"))).toBeLessThan(
      lightness(dark.get("--foreground")),
    );
    expect(lightness(light.get("--background"))).toBeGreaterThan(
      lightness(light.get("--foreground")),
    );
  });

  it("does not share values beyond the ones documented as intentional", () => {
    const shared = [...dark.keys()].filter(
      (t) => light.has(t) && light.get(t) === dark.get(t),
    );
    const undocumented = shared.filter((t) => !(t in INTENTIONALLY_SHARED));

    expect(
      undocumented,
      `these tokens are identical in both themes: ${undocumented.join(", ")}. If that is ` +
        `deliberate, add each to INTENTIONALLY_SHARED with the reason; otherwise the dark ` +
        `theme is a partial copy of the light one.`,
    ).toEqual([]);
  });

  it("keeps muted text legible on a dark surface", () => {
    expect(
      lightness(dark.get("--muted-foreground")),
      "--muted-foreground is too dark to read against --muted in dark mode",
    ).toBeGreaterThan(lightness(dark.get("--muted")) + 0.2);
  });

  it("defines the Feature 006 roles the shadcn set lacks", () => {
    for (const t of ["--surface-raised", "--border-strong", "--foreground-2"]) {
      expect(light.has(t), `${t} missing from :root`).toBe(true);
      expect(dark.has(t), `${t} missing from .dark`).toBe(true);
    }
  });
});

describe("the theme provider", () => {
  const layout = readFileSync(
    join(__dirname, "..", "..", "src", "app", "layout.tsx"),
    "utf8",
  );
  const settings = readFileSync(
    join(
      __dirname,
      "..",
      "..",
      "src",
      "components",
      "workspace",
      "settings",
      "appearance-settings-page.tsx",
    ),
    "utf8",
  );

  it("enables system support if the settings page offers a System option", () => {
    const offersSystem = /id:\s*"system"/.test(settings);
    const enablesSystem = /enableSystem(?!\s*=\s*\{false\})/.test(layout);

    expect(
      !offersSystem || enablesSystem,
      "the settings page offers a System theme while the provider has enableSystem={false}. " +
        "That control cannot work, and a control that cannot work is worse than an absent one.",
    ).toBe(true);
  });
});
