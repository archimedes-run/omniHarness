import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * T088 — no Feature 004 surface hardcodes a colour (FR-033).
 *
 * Extends the sidebar token check to every new surface's components and page.
 * A SOURCE check, paired with the rendering one (tests/rendering/theme.spec.ts,
 * SC-013): that one proves the surfaces change with the theme; this one names
 * the file and the literal when one does not.
 */

const SRC = join(__dirname, "..", "..", "src");
// Phase 2.5 moved these: tool sources into settings/connections, policy into
// settings/safety and the activity log, triggers into automations.
const SURFACES = [
  "confirmations",
  "connections",
  "sessions",
  "triggers",
  "policy",
  "inbox",
  "automations",
];
const DIRS = SURFACES.flatMap((s) => [
  join(SRC, "components", "workspace", s),
  join(SRC, "app", "workspace", s),
]);

const PALETTE =
  "(?:slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)-\\d{2,3}";
const UTILITY =
  "(?:text|bg|border|ring|fill|stroke|from|via|to|outline|divide|placeholder|decoration|accent|caret|shadow)";
const HARDCODED = [
  new RegExp(`\\b${UTILITY}-(?:black|white|${PALETTE})(?:/\\d+)?\\b`, "g"),
  /#[0-9a-fA-F]{3,8}\b/g,
  /\b(?:rgb|rgba|hsl|hsla)\(/g,
];

function files(dir: string): string[] {
  try {
    statSync(dir);
  } catch {
    return [];
  }
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory()
      ? files(path)
      : /\.tsx?$/.test(name)
        ? [path]
        : [];
  });
}

function offences(source: string): string[] {
  return HARDCODED.flatMap((re) => [...source.matchAll(re)].map((m) => m[0]));
}

describe("Feature 004 surfaces take their colours from tokens (FR-033)", () => {
  it("POSITIVE CONTROL: the check sees a hardcoded colour when shown one", () => {
    expect(
      offences('className="text-red-500 bg-white" style={{ color: "#333" }}'),
    ).toEqual(["text-red-500", "bg-white", "#333"]);
    expect(
      offences('className="text-muted-foreground bg-muted border-border"'),
    ).toEqual([]);
  });

  it("covers every surface it names", () => {
    for (const surface of SURFACES) {
      expect(
        DIRS.flatMap(files).some((f) => f.includes(`/${surface}/`)),
        `no files found for ${surface}; the check is blind to it`,
      ).toBe(true);
    }
  });

  it("finds no hardcoded colour in any surface", () => {
    const found = DIRS.flatMap(files).flatMap((f) =>
      offences(readFileSync(f, "utf8")).map((o) => `${relative(SRC, f)}: ${o}`),
    );
    expect(found, `hardcoded colours:\n${found.join("\n")}`).toEqual([]);
  });
});
