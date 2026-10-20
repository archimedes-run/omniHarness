/**
 * The one logo registry (Feature 006). Every place that shows where something
 * comes from (a model provider, a connector, an MCP server) asks this table,
 * so a brand is drawn the same way everywhere and an unknown source falls back
 * to the same neutral monogram.
 *
 * Two kinds of logo, both recorded in THIRD-PARTY-NOTICES.md (Logos):
 *   - "file": the brand's own full-colour SVG, served from public/brand/,
 *     never recoloured (Google product icons, from Google's own CDN);
 *   - "mark": a monochrome mark (marks.ts, Simple Icons 16.33.0), drawn in
 *     the theme's foreground, as black or white, which those brands allow.
 * A brand with neither (OpenAI, Slack, Outlook: no SVG obtainable from an
 * official or CC0 source here) shows its monogram until one is added.
 */

export interface BrandEntry {
  /** Canonical id: lowercase, letters and digits only. */
  id: string;
  /** The brand's own name, used for the accessible name ("Gmail logo"). */
  name: string;
  /** Up to three characters for the neutral monogram. */
  monogram: string;
  /** Other spellings the app uses for the same source. */
  aliases?: string[];
  logo?: { kind: "file"; src: string } | { kind: "mark" };
}

const FILE = (file: string) => ({
  kind: "file" as const,
  src: `/brand/${file}`,
});
const MARK = { kind: "mark" as const };

export const BRANDS: readonly BrandEntry[] = [
  // Model providers / coding agents.
  {
    id: "anthropic",
    name: "Anthropic",
    monogram: "A",
    aliases: ["claude", "claudecode"],
    logo: MARK,
  },
  {
    id: "openai",
    name: "OpenAI",
    monogram: "OAI",
    aliases: ["codex", "chatgpt", "gpt"],
  },
  // Composio toolkits (backend/app/gateway/routers/composio.py TOOLKIT_CATALOG).
  { id: "gmail", name: "Gmail", monogram: "M", logo: FILE("gmail.svg") },
  {
    id: "googlecalendar",
    name: "Google Calendar",
    monogram: "31",
    aliases: ["gcal"],
    logo: FILE("googlecalendar.svg"),
  },
  {
    id: "googledrive",
    name: "Google Drive",
    monogram: "GD",
    aliases: ["gdrive"],
    logo: FILE("googledrive.svg"),
  },
  {
    id: "github",
    name: "GitHub",
    monogram: "GH",
    aliases: ["githubissueconnector"],
    logo: MARK,
  },
  { id: "slack", name: "Slack", monogram: "S" },
  { id: "notion", name: "Notion", monogram: "N", logo: MARK },
  { id: "linear", name: "Linear", monogram: "L", logo: MARK },
  {
    id: "outlook",
    name: "Outlook",
    monogram: "O",
    aliases: ["microsoftoutlook"],
  },
  // Local MCP servers that are products with a brand of their own.
  {
    id: "postgres",
    name: "PostgreSQL",
    monogram: "PG",
    aliases: ["postgresql"],
    logo: MARK,
  },
];

const BY_KEY: ReadonlyMap<string, BrandEntry> = new Map(
  BRANDS.flatMap((b) => [b.id, ...(b.aliases ?? [])].map((k) => [k, b])),
);

/**
 * "connector:GOOGLECALENDAR", "local:github", "composio-gmail", "Google
 * Calendar", "claude" → one key. Namespaces and separators carry no brand.
 */
export function normaliseSourceId(raw: string): string {
  return raw
    .trim()
    .toLowerCase()
    .replace(/^(connector|local|mcp):/, "")
    .replace(/^(composio|connector)[-_]/, "")
    .replace(/[^a-z0-9]/g, "");
}

export function resolveBrand(
  raw: string | null | undefined,
): BrandEntry | undefined {
  if (!raw) return undefined;
  return BY_KEY.get(normaliseSourceId(raw));
}

/** The neutral fallback: initials of the words, or the first two letters. */
export function monogramFor(name: string): string {
  const words = name
    .replace(/^(connector|local|mcp):/i, "")
    .split(/[\s_\-.:/]+/)
    .filter(Boolean);
  if (words.length === 0) return "?";
  if (words.length === 1) {
    const w = words[0]!;
    return (w[0]!.toUpperCase() + (w[1] ?? "")).slice(0, 2);
  }
  return words
    .slice(0, 2)
    .map((w) => w[0]!.toUpperCase())
    .join("");
}
