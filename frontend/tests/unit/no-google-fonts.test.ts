import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * The app ships its fonts (public/fonts/, SIL OFL 1.1) and never talks to Google
 * Fonts: not at build time (CI's runner cannot reach it, and next/font/google
 * failed the build there) and not at runtime (no page asks a font CDN for
 * anything). Any import of next/font/google, or any reference to
 * fonts.googleapis.com / fonts.gstatic.com, in the app's source, config or
 * public files (the demo thread artifacts included) fails this test.
 */

const FRONTEND = join(__dirname, "..", "..");

const FORBIDDEN = [
  /next\/font\/google/,
  /fonts\.googleapis\.com/,
  /fonts\.gstatic\.com/,
];

/** Scanned roots, relative to frontend/. */
const ROOTS = ["src", "public"];

/** Top-level files in frontend/ that are scanned too (configs, Dockerfile). */
const TOP_LEVEL = /\.(?:[cm]?[jt]sx?|json|css)$|^Dockerfile$/;
const TOP_LEVEL_SKIP = new Set(["package.json", "pnpm-lock.yaml"]);

const TEXT =
  /\.(?:[cm]?[jt]sx?|css|scss|html|json|md|mdx|svg|txt|webmanifest)$/;

function walk(dir: string, out: string[]): void {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) walk(path, out);
    else if (TEXT.test(name)) out.push(path);
  }
}

function scannedFiles(): string[] {
  const files: string[] = [];
  for (const root of ROOTS) walk(join(FRONTEND, root), files);
  for (const name of readdirSync(FRONTEND)) {
    const path = join(FRONTEND, name);
    if (TOP_LEVEL_SKIP.has(name) || !TOP_LEVEL.test(name)) continue;
    if (statSync(path).isFile()) files.push(path);
  }
  return files;
}

function offenders(files: string[]): string[] {
  const found: string[] = [];
  for (const file of files) {
    const lines = readFileSync(file, "utf8").split("\n");
    lines.forEach((line, i) => {
      if (FORBIDDEN.some((re) => re.test(line))) {
        found.push(`${relative(FRONTEND, file)}:${i + 1}: ${line.trim()}`);
      }
    });
  }
  return found;
}

describe("fonts ship with the app (no Google Fonts)", () => {
  it("scans the layout and the stylesheet that load the fonts", () => {
    const scanned = scannedFiles().map((f) => relative(FRONTEND, f));
    // A guard that silently scans nothing proves nothing.
    expect(scanned).toContain(join("src", "app", "layout.tsx"));
    expect(scanned).toContain(join("src", "styles", "globals.css"));
    expect(scanned).toContain("next.config.js");
  });

  it("no source imports next/font/google or references Google's font hosts", () => {
    expect(offenders(scannedFiles())).toEqual([]);
  });

  it("the shipped font files and their OFL notice are present", () => {
    const fonts = join(FRONTEND, "public", "fonts");
    for (const name of [
      "inter-latin.woff2",
      "inter-latin-ext.woff2",
      "jetbrains-mono-latin.woff2",
      "jetbrains-mono-latin-ext.woff2",
      "fonts.css",
    ]) {
      expect(statSync(join(fonts, name)).size).toBeGreaterThan(500);
    }
    for (const [file, holder] of [
      ["Inter-OFL.txt", "The Inter Project Authors"],
      ["JetBrainsMono-OFL.txt", "The JetBrains Mono Project Authors"],
    ] as const) {
      const ofl = readFileSync(join(fonts, file), "utf8");
      expect(ofl).toContain(holder);
      expect(ofl).toContain("SIL OPEN FONT LICENSE Version 1.1");
    }
  });
});
