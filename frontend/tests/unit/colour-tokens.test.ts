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
  "components/landing/sections/what-is-omniharness-section.tsx": {
    reason:
      "soft drop shadow, a slate tint at 8% or less, that reads in both themes",
    literals: ["rgba("],
  },
  "components/landing/sections/features-section.tsx": {
    reason:
      "soft drop shadow, a slate tint at 8% or less, that reads in both themes",
    literals: ["rgba("],
  },
  "components/landing/sections/example-harnesses-section.tsx": {
    reason:
      "soft drop shadow, a slate tint at 8% or less, that reads in both themes",
    literals: ["rgba("],
  },
  "components/landing/header.tsx": {
    reason:
      "soft drop shadow, a slate tint at 8% or less, that reads in both themes",
    literals: ["rgba("],
  },
  "app/workspace/chats/[thread_id]/page.tsx": {
    reason: "not a colour: an issue number (#2746) in a comment",
    literals: ["#2746"],
  },
  "components/landing/hero.tsx": {
    reason: "decorative glow (rgba) behind the hero",
    literals: ["rgba("],
  },
  "components/landing/progressive-skills-animation.tsx": {
    reason: "always-dark terminal panel (zinc) in both themes",
    literals: [
      "bg-blue-600",
      "bg-zinc-800",
      "bg-zinc-900/50",
      "border-zinc-700",
      "border-zinc-800",
      "text-blue-400",
      "text-purple-400",
      "text-white",
      "text-zinc-300",
      "text-zinc-400",
      "text-zinc-500",
      "text-zinc-600",
    ],
  },
  "components/landing/section.tsx": {
    reason: "decorative heading gradient",
    literals: ["from-white", "to-gray-400", "via-gray-200"],
  },
  "components/landing/sections/agent-skills-section.tsx": {
    reason:
      "always-dark agent-log panel and diagram (stone-950) in both themes; a soft drop shadow (rgba)",
    literals: [
      "rgba(",
      "#111827",
      "#1c1917",
      "#6b7280",
      "#94a3b8",
      "#9ca3af",
      "#a8a29e",
      "#cbd5e1",
      "#d6d3d1",
      "#e7e5e4",
      "#f5f5f4",
      "#ffffff",
      "bg-stone-500",
      "bg-stone-700",
      "bg-stone-950",
      "border-stone-800",
      "shadow-stone-900/10",
      "text-emerald-400",
      "text-emerald-400/80",
      "text-sky-400/80",
      "text-stone-100",
      "text-stone-200",
      "text-stone-300",
      "text-stone-400",
    ],
  },
  "components/landing/sections/case-study-section.tsx": {
    reason: "image overlay: white text and shadow over a photo",
    literals: ["rgba(", "shadow-black", "text-white/85"],
  },
  "components/landing/sections/community-section.tsx": {
    reason: "decorative particle colours",
    literals: ["#60A5FA", "#A560FA", "#A5FA60"],
  },
  "components/landing/sections/final-cta-section.tsx": {
    reason:
      "always-dark call-to-action card (stone-950, white text) in both themes; a soft drop shadow (rgba)",
    literals: [
      "rgba(",
      "bg-stone-100",
      "bg-stone-950",
      "bg-white",
      "bg-white/10",
      "bg-white/6",
      "border-white/16",
      "text-stone-950",
      "text-white",
      "text-white/55",
      "text-white/70",
    ],
  },
  "components/landing/sections/harness-definition-section.tsx": {
    reason: "decorative gradient bar; a soft drop shadow (rgba)",
    literals: ["rgba(", "from-stone-900", "to-stone-200", "via-stone-500"],
  },
  "components/landing/sections/live-preview-demo-section.tsx": {
    reason:
      "mock app: always-dark code editor and file tree, syntax colours, macOS window dots",
    literals: [
      "#111111",
      "#1a1a1a",
      "#34d399",
      "#3b82f6",
      "#4ade80",
      "#60a5fa",
      "#78716c",
      "#93c5fd",
      "#a8a29e",
      "#d6d3d1",
      "#dbeafe",
      "#ef4444",
      "#f59e0b",
      "#f5f5f4",
      "#fb923c",
      "#fbbf24",
      "#fde047",
      "#fde68a",
      "bg-blue-500",
      "bg-green-500",
      "bg-red-500",
      "bg-stone-300",
      "bg-stone-700",
      "bg-stone-800",
      "bg-yellow-500",
      "border-stone-800",
      "shadow-stone-200/60",
      "text-stone-200",
      "text-stone-400",
      "text-white",
      "text-white/60",
      "text-white/80",
    ],
  },
  "components/landing/sections/sandbox-section.tsx": {
    reason: "always-dark sandbox chips (zinc) in both themes",
    literals: [
      "bg-zinc-900",
      "border-zinc-800",
      "text-blue-500",
      "text-purple-400",
      "text-zinc-300",
      "text-zinc-400",
    ],
  },
  "components/landing/sections/whats-new-section.tsx": {
    reason: "decorative backdrop colour",
    literals: ["#0a0a0a"],
  },
  "components/ui/aurora-text.tsx": {
    reason: "visual effect: the colours are its parameters",
    literals: ["#0070F3", "#38bdf8", "#7928CA", "#FF0080"],
  },

  "components/ui/flickering-grid.tsx": {
    reason: "visual effect: computes its own rgba from the colour it is given",
    literals: ["rgb(", "rgba("],
  },
  "components/ui/magic-bento.tsx": {
    reason: "visual effect: glow colour parameter",
    literals: ["rgba("],
  },

  "components/ui/shine-border.tsx": {
    reason: "visual effect: the colours are its parameters",
    literals: ["#000000", "#fff"],
  },
  "components/ui/spotlight-card.tsx": {
    reason: "visual effect: spotlight rgba",
    literals: ["rgba("],
  },
  "components/ui/terminal.tsx": {
    reason: "macOS window dots (red, yellow, green)",
    literals: ["bg-green-500", "bg-red-500", "bg-yellow-500"],
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
    reason:
      "an issue number (#2746) in a comment; the send button's violet-indigo gradient is a brand accent; the red glow (rgb) on the ultra mode's rocket (this file is being rebuilt by the chat-bar work, so it is listed, not edited)",
    literals: ["#2746", "from-violet-400", "rgb(", "to-indigo-500"],
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
