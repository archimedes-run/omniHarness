import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * The sidebar's text colour must come from a theme token, never a literal.
 *
 * The occasion: `sidebarMenuButtonVariants` hardcoded `text-black` in its base
 * classes, while hover applied `text-sidebar-accent-foreground`. In light mode
 * that reads as normal. In dark mode the sidebar is dark and the label was
 * black on near-black — INVISIBLE UNTIL HOVERED, which is how it was reported.
 *
 * This is a SOURCE check, and source checks are exactly what missed the last
 * two theme bugs. It is here because the honest alternative is unavailable:
 * the sidebar only renders under /workspace, which redirects to /setup or
 * /login without a backend, so a rendering assertion there would be testing
 * whether the API is up. Stated as a limit rather than papered over —
 * `tests/rendering/theme.spec.ts` covers what CAN be rendered.
 */

const SIDEBAR = readFileSync(
  join(__dirname, "..", "..", "src", "components", "ui", "sidebar.tsx"),
  "utf8",
);

describe("the sidebar takes its colours from tokens", () => {
  it("does not hardcode a text colour on the menu button", () => {
    const start = SIDEBAR.indexOf("const sidebarMenuButtonVariants");
    expect(
      start,
      "sidebarMenuButtonVariants has been renamed; this test is now blind",
    ).toBeGreaterThan(-1);

    // The base class string, up to the variants object.
    const base = SIDEBAR.slice(start, SIDEBAR.indexOf("variants:", start));
    const literals = base.match(/\btext-(black|white)\b/g) ?? [];

    expect(
      literals,
      `sidebarMenuButtonVariants hardcodes ${literals.join(", ")}. The sidebar ` +
        `background is a theme token, so a literal text colour is legible in ` +
        `exactly one theme — this shipped as a label invisible until hovered.`,
    ).toEqual([]);
  });
});
