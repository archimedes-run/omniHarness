import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { MONO_PATHS } from "@/components/brand/marks";
import {
  BRANDS,
  monogramFor,
  normaliseSourceId,
  resolveBrand,
} from "@/components/brand/registry";

const ROOT = join(__dirname, "..", "..");
const NOTICES = readFileSync(
  join(ROOT, "..", "THIRD-PARTY-NOTICES.md"),
  "utf8",
);

describe("logo registry (Feature 006)", () => {
  it.each([
    ["connector:GOOGLECALENDAR", "googlecalendar"],
    ["GMAIL", "gmail"],
    ["local:github", "github"],
    ["composio-slack", "slack"],
    ["Google Drive", "googledrive"],
    ["claude", "anthropic"],
    ["codex", "openai"],
    ["local:postgres", "postgres"],
  ])("%s resolves to %s", (raw, id) => {
    expect(resolveBrand(raw)?.id).toBe(id);
  });

  it("an unknown source has no brand and gets a neutral monogram", () => {
    expect(resolveBrand("local:session-watcher")).toBeUndefined();
    expect(monogramFor("session-watcher")).toBe("SW");
    expect(monogramFor("weather")).toBe("We");
  });

  it("covers every Composio toolkit the gateway offers", () => {
    const composio = readFileSync(
      join(ROOT, "..", "backend/app/gateway/routers/composio.py"),
      "utf8",
    );
    const slugs = [...composio.matchAll(/"slug": "([A-Z]+)"/g)].map(
      (m) => m[1]!,
    );
    expect(slugs.length).toBeGreaterThanOrEqual(8);
    for (const slug of slugs) expect(resolveBrand(slug), slug).toBeDefined();
  });

  it("every file logo exists, is a clean SVG, and is in THIRD-PARTY-NOTICES", () => {
    for (const b of BRANDS) {
      if (b.logo?.kind !== "file") continue;
      const path = join(ROOT, "public", b.logo.src);
      expect(existsSync(path), b.logo.src).toBe(true);
      const svg = readFileSync(path, "utf8");
      expect(svg, `${b.id}: scripts, handlers or external refs`).not.toMatch(
        /<script|\son\w+=|href=|url\(|<image|<foreignObject/i,
      );
      expect(NOTICES, `${b.id} missing from notices`).toContain(
        b.logo.src.replace(/^\//, "frontend/public/"),
      );
    }
  });

  it("every mark has path data, and every brand with a logo is in THIRD-PARTY-NOTICES", () => {
    for (const b of BRANDS) {
      if (b.logo?.kind === "mark") expect(MONO_PATHS[b.id], b.id).toMatch(/^M/);
      if (b.logo) expect(NOTICES, b.name).toContain(b.name);
    }
  });

  it("normalises namespaces and separators away", () => {
    expect(normaliseSourceId("connector:Google_Calendar")).toBe(
      "googlecalendar",
    );
  });
});
