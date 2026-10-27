import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * No hardcoded colour anywhere in the frontend (Phase 2.5 colour pass; this
 * began as Feature 004's T088, scoped to its five surfaces).
 *
 * Colours come from the theme tokens (src/styles/globals.css), which have a
 * light and a dark value. A palette class (text-stone-400, bg-white), a hex
 * literal or an rgb()/hsl() literal is fixed in both themes; before this pass
 * there were 1,025 of them, and the landing page and the MCP pages did not
 * follow the theme at all.
 *
 * What is left is listed in ALLOWED, per file and per literal, each file with
 * the reason its colours are fixed on purpose (an always-dark panel, a visual
 * effect, the theme previews, an issue number in a comment). A new literal
 * fails even in a listed file, and a listed literal that no longer appears
 * fails as stale. tests/rendering/contrast.spec.ts measures the result: every
 * text element in both themes meets WCAG AA.
 */

const SRC = join(__dirname, "..", "..", "src");

const PALETTE =
  "(?:slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)-\\d{2,3}";
const UTILITY =
  "(?:text|bg|border|ring|fill|stroke|from|via|to|outline|divide|placeholder|decoration|accent|caret|shadow)";
// No leading \b on the function literals: inside an arbitrary Tailwind value
// (`shadow-[0_0_0_1px_hsl(...)]`) the `_` before them is a word character, so
// \b never matched there and that literal went unseen.
const HARDCODED = [
  new RegExp(`\\b${UTILITY}-(?:black|white|${PALETTE})(?:/\\d+)?\\b`, "g"),
  /#[0-9a-fA-F]{3,8}\b/g,
  /(?<![a-zA-Z-])(?:rgb|rgba|hsl|hsla|oklch|oklab|lab|lch)\(/g,
];

/**
 * Directories that are not scanned, each with the reason. Everything else
 * under src/ is, including directories added later (the walk is recursive and
 * the coverage test below fails if a component directory is ever skipped).
 */
const EXEMPT_DIRS: Record<string, string> = {
  "components/brand":
    "official brand logos keep their trademark colours in both themes (TOKEN-CONTRACT: logos are the one exception, via the logo registry only)",
};
const exempt = (rel: string) =>
  Object.keys(EXEMPT_DIRS).some((d) => rel === d || rel.startsWith(`${d}/`));

const ALLOWED: Record<string, { reason: string; literals: string[] }> = {
  "core/agents/avatars.ts": {
    reason:
      "each avatar's disc colour, the same one painted inside its SVG artwork (public/avatars): the face looks the same in both themes, like a photo",
    literals: [
      "#2C69AD",
      "#C02B2B",
      "#23826B",
      "#8A46C8",
      "#55657C",
      "#8A6A00",
      "#BE2E80",
      "#4C5ED2",
      "#C2470A",
      "#7052DC",
      "#136C93",
      "#9A2FB0",
      "#5E7A12",
      "#2C7A44",
      "#BA2E54",
      "#9C5628",
      "#4560CC",
      "#2F7480",
      "#B23E76",
      "#0E6F7E",
    ],
  },
  "app/workspace/chats/[thread_id]/page.tsx": {
    reason: "not a colour: an issue number (#2746) in a comment",
    literals: ["#2746"],
  },

  "components/ui/aurora-text.tsx": {
    reason: "visual effect: the colours are its parameters",
    literals: ["#0070F3", "#38bdf8", "#7928CA", "#FF0080"],
  },

  "components/ui/flickering-grid.tsx": {
    reason: "visual effect: computes its own rgba from the colour it is given",
    literals: ["rgb(", "rgba("],
  },

  "components/ui/shine-border.tsx": {
    reason: "visual effect: the colours are its parameters",
    literals: ["#000000", "#fff"],
  },
  "components/ui/spotlight-card.tsx": {
    reason: "visual effect: spotlight rgba",
    literals: ["rgba("],
  },

  "components/ui/word-rotate.tsx": {
    reason: "decorative gold gradient on rotating words",
    literals: ["#e3a812", "#e9c665", "#efefbb"],
  },
  "components/workspace/artifacts/artifact-file-detail.tsx": {
    reason: "always-dark VS Code-style file explorer and editor chrome",
    literals: [
      "#000000",
      "#1e1e1e",
      "#2a2d2e",
      "#37373d",
      "#3c3c3c",
      "#666",
      "#75beff",
      "#888",
      "#cccccc",
      "#e8c17a",
      "text-white",
    ],
  },
  "components/workspace/code-editor.tsx": {
    reason: "code editor theme colours (fixed light and dark themes)",
    literals: ["#000000", "#4a4a4a", "#aaaaaa"],
  },
  "components/workspace/input-box.tsx": {
    reason: "not a colour: an issue number (#2746) in a comment",
    literals: ["#2746"],
  },
  "components/workspace/mcp/mcp-server-detail.tsx": {
    reason: "always-dark code editor and build log (#13141a)",
    literals: [
      "#13141a",
      "#131519",
      "#4a5060",
      "#7C79F0",
      "#9CA3AF",
      "#E9EBF0",
      "rgba(",
    ],
  },
  "components/workspace/messages/subtask-card.tsx": {
    reason: "decorative shimmer gradient on a running subtask",
    literals: ["#A07CFE", "#FE8FB5", "#FFBE7B"],
  },

  "components/workspace/welcome.tsx": {
    reason: "decorative gold gradient on the greeting",
    literals: ["#e3a812", "#e9c665", "#efefbb"],
  },
  "core/messages/usage.ts": {
    reason: "not a colour: a PR number (#1218) in a comment",
    literals: ["#1218"],
  },
};
function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (exempt(relative(SRC, path))) return [];
    return statSync(path).isDirectory()
      ? files(path)
      : /\.tsx?$/.test(name)
        ? [path]
        : [];
  });
}

function literals(source: string): string[] {
  return [
    ...new Set(
      HARDCODED.flatMap((re) => [...source.matchAll(re)].map((m) => m[0])),
    ),
  ];
}

const FOUND = new Map(
  files(SRC)
    .map((f) => [relative(SRC, f), literals(readFileSync(f, "utf8"))] as const)
    .filter(([, l]) => l.length > 0),
);

describe("colours come from theme tokens, site-wide", () => {
  it("POSITIVE CONTROL: the check sees a hardcoded colour when shown one", () => {
    expect(
      literals('className="text-red-500 bg-white" style={{ color: "#333" }}'),
    ).toEqual(["text-red-500", "bg-white", "#333"]);
    expect(literals('className="shadow-[0_0_0_1px_hsl(var(--x))]"')).toEqual([
      "hsl(",
    ]);
    expect(literals('style={{ color: "oklch(0.5 0 0)" }}')).toEqual(["oklch("]);
    expect(
      literals('className="text-muted-foreground bg-muted border-border"'),
    ).toEqual([]);
  });

  it("finds no hardcoded colour that is not listed, with its reason", () => {
    const unlisted = [...FOUND].flatMap(([file, found]) =>
      found
        .filter((l) => !ALLOWED[file]?.literals.includes(l))
        .map((l) => `${file}: ${l}`),
    );
    expect(
      unlisted,
      `use a theme token, or list it with the reason it is fixed:\n${unlisted.join("\n")}`,
    ).toEqual([]);
  });

  it("lists nothing that is no longer there", () => {
    const stale = Object.entries(ALLOWED).flatMap(([file, entry]) =>
      entry.literals
        .filter((l) => !FOUND.get(file)?.includes(l))
        .map((l) => `${file}: ${l}`),
    );
    expect(stale, "remove these from ALLOWED").toEqual([]);
  });

  it("scans every component directory, new ones included", () => {
    const dirs = (dir: string): string[] =>
      readdirSync(dir).flatMap((name) => {
        const path = join(dir, name);
        return statSync(path).isDirectory() ? [path, ...dirs(path)] : [];
      });
    const scanned = new Set(files(SRC).map((f) => dirname(f)));
    const missed = dirs(join(SRC, "components"))
      .filter((d) => !exempt(relative(SRC, d)))
      .filter((d) => readdirSync(d).some((n) => /\.tsx?$/.test(n)))
      .filter((d) => !scanned.has(d))
      .map((d) => relative(SRC, d));
    expect(missed, "these component directories are not scanned").toEqual([]);
    expect(scanned.size).toBeGreaterThan(10);
  });

  it("scans the landing page and allows it no fixed colour at all", () => {
    // The landing page follows the theme in both modes (Graphite tokens
    // only): no exception may be listed for it, and its files are scanned.
    const landing = files(SRC)
      .map((f) => relative(SRC, f))
      .filter(
        (f) => f.startsWith("components/landing/") || f === "app/page.tsx",
      );
    expect(landing).toEqual(
      expect.arrayContaining([
        "app/page.tsx",
        "components/landing/hero.tsx",
        "components/landing/header.tsx",
        "components/landing/footer.tsx",
        "components/landing/sections/safety-section.tsx",
      ]),
    );
    expect(
      Object.keys(ALLOWED).filter((f) => landing.includes(f)),
      "the landing page uses theme tokens only",
    ).toEqual([]);
  });

  it("exempts directories only with a reason", () => {
    expect(
      Object.entries(EXEMPT_DIRS)
        .filter(([, r]) => !r.trim())
        .map(([d]) => d),
    ).toEqual([]);
  });

  it("gives every listed file a reason", () => {
    expect(
      Object.entries(ALLOWED)
        .filter(([, e]) => !e.reason.trim())
        .map(([f]) => f),
    ).toEqual([]);
  });
});
