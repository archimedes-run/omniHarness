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

  it("every file logo exists, is a clean SVG or a real PNG, and is in THIRD-PARTY-NOTICES", () => {
    for (const b of BRANDS) {
      const files =
        b.logo?.kind === "file"
          ? [b.logo.src]
          : b.logo?.kind === "themed"
            ? [b.logo.light, b.logo.dark]
            : [];
      for (const src of files) {
        const path = join(ROOT, "public", src);
        expect(existsSync(path), src).toBe(true);
        if (src.endsWith(".png")) {
          const head = readFileSync(path).subarray(0, 8).toString("hex");
          expect(head, `${src} is not a PNG`).toBe("89504e470d0a1a0a");
        } else {
          const svg = readFileSync(path, "utf8");
          expect(
            svg,
            `${b.id}: scripts, handlers or external refs`,
          ).not.toMatch(/<script|\son\w+=|href=|url\(|<image|<foreignObject/i);
        }
        expect(NOTICES, `${src} missing from notices`).toContain(
          src.replace(/^\//, "frontend/public/"),
        );
      }
    }
  });

  it("OpenAI and Slack use their official assets; Outlook stays a monogram", () => {
    const by = (id: string) => BRANDS.find((b) => b.id === id)!;
    expect(by("openai").logo).toMatchObject({
      kind: "themed",
      light: "/brand/openai-blossom-black.svg",
      dark: "/brand/openai-blossom-white.svg",
    });
    expect(by("slack").logo).toEqual({ kind: "file", src: "/brand/slack.png" });
    expect(by("outlook").logo).toBeUndefined();
  });

  it("OpenAI's ink is the share of its file the Blossom really spans", () => {
    // The pack's SVG keeps its own clear space; BrandLogo scales by 1 / ink so
    // the Blossom draws as large as Anthropic's mark (home.spec.ts measures it).
    const logo = BRANDS.find((b) => b.id === "openai")!.logo;
    if (logo?.kind !== "themed") throw new Error("openai is not themed");
    for (const src of [logo.light, logo.dark]) {
      const svg = readFileSync(join(ROOT, "public", src), "utf8");
      const box = Number(/viewBox="0 0 (\d+(?:\.\d+)?)/.exec(svg)![1]);
      const d = /<path d="([^"]+)"/.exec(svg)![1]!;
      const xs = [...d.matchAll(/-?\d+(?:\.\d+)?/g)]
        .map((m) => Number(m[0]))
        .filter((_, i) => i % 2 === 0);
      const spans = (Math.max(...xs) - Math.min(...xs)) / box;
      expect(logo.ink, src).toBeCloseTo(spans, 2);
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
