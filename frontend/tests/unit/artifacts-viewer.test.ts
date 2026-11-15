import { describe, expect, it } from "vitest";

import { hasChanges, lineDiff } from "@/core/artifacts/line-diff";
import {
  checkChip,
  downloadForms,
  lineageWords,
  sourceChip,
  versionSummary,
} from "@/core/artifacts/store-logic";

/**
 * The artifact viewer's words: the source chip rule (neutral unless the
 * version came from content AND its kind can run code; never "(unknown)"),
 * the checks chip, the versions drawer's summaries, the download forms per
 * kind, and the Compare line diff.
 */
describe("source chip", () => {
  it("is neutral 'From your request' for the owner's own request", () => {
    for (const kind of ["react", "markdown"] as const) {
      expect(sourceChip(kind, "user", null)).toEqual({
        label: "From your request",
        tone: "neutral",
      });
    }
  });

  it("warns only for content-originated code that runs", () => {
    for (const kind of ["html", "react", "webapp"] as const) {
      expect(sourceChip(kind, "content", "web_fetch")).toEqual({
        label: "From content the assistant read (web_fetch)",
        tone: "warn",
      });
    }
  });

  it("is neutral for content-originated static kinds", () => {
    for (const kind of [
      "markdown",
      "code",
      "svg",
      "mermaid",
      "chart",
      "image",
      "file",
    ] as const) {
      expect(sourceChip(kind, "content", null)).toEqual({
        label: "Made from what the assistant read",
        tone: "neutral",
      });
    }
  });

  it("never prints (unknown) or an empty parenthetical", () => {
    for (const source of [null, "", "unknown", "Unknown", " ​"]) {
      const chip = sourceChip("react", "content", source);
      expect(chip.label).toBe("From content the assistant read");
      expect(chip.label).not.toMatch(/\(/);
      expect(lineageWords("content", source)).toBe(
        "Made from content the assistant read",
      );
    }
  });

  it("an imported file says so", () => {
    expect(sourceChip("html", "import", "a file from this chat")).toEqual({
      label: "Imported from its chat",
      tone: "neutral",
    });
  });
});

describe("checks chip", () => {
  it("short words per state", () => {
    expect(checkChip("passed")).toEqual({ label: "Checked", tone: "ok" });
    expect(checkChip("failed")).toEqual({
      label: "Check failed",
      tone: "warn",
    });
    expect(checkChip("pending").tone).toBe("neutral");
    expect(checkChip("not_checked")).toEqual({
      label: "Not checked",
      tone: "neutral",
    });
    expect(checkChip(null).tone).toBe("neutral");
  });
});

describe("version summaries", () => {
  it("the note, trimmed to one short line; First version when none", () => {
    expect(
      versionSummary({ n: 2, note: "Fixed the phone layout", origin: "tool" }),
    ).toBe("Fixed the phone layout");
    expect(versionSummary({ n: 1, note: null, origin: "tool" })).toBe(
      "First version",
    );
    expect(versionSummary({ n: 3, note: "", origin: "restore" })).toBe(
      "Restored",
    );
    const long = versionSummary({
      n: 2,
      note: "word ".repeat(60),
      origin: "tool",
    });
    expect(long.length).toBeLessThanOrEqual(90);
    expect(long.endsWith("…")).toBe(true);
    expect(versionSummary({ n: 2, note: "a\n\nb", origin: "tool" })).toBe(
      "a b",
    );
  });
});

describe("download forms per kind", () => {
  it("lists only what the download route offers", () => {
    expect(downloadForms("react").map((f) => f.form)).toEqual([
      "page",
      "source",
    ]);
    expect(downloadForms("html", false).map((f) => f.form)).toEqual(["source"]);
    expect(downloadForms("webapp")).toEqual([
      { form: "page", label: "Files (.zip)" },
    ]);
    for (const kind of ["markdown", "code", "svg", "image", "file"] as const) {
      expect(downloadForms(kind)).toHaveLength(1);
    }
  });
});

describe("line diff", () => {
  it("marks added and removed lines and collapses long unchanged runs", () => {
    const a = Array.from({ length: 20 }, (_, i) => `line ${i}`);
    const b = [...a];
    b[10] = "changed";
    const rows = lineDiff(a.join("\n"), b.join("\n"), 2)!;
    expect(rows[0]).toEqual({ type: "skip", count: 8 });
    expect(rows.filter((r) => r.type === "del")).toEqual([
      { type: "del", text: "line 10" },
    ]);
    expect(rows.filter((r) => r.type === "add")).toEqual([
      { type: "add", text: "changed" },
    ]);
    expect(rows[rows.length - 1]).toEqual({ type: "skip", count: 7 });
    expect(hasChanges(rows)).toBe(true);
  });

  it("no changes, empty sides, and a cap", () => {
    expect(hasChanges(lineDiff("a\nb", "a\nb")!)).toBe(false);
    expect(lineDiff("", "x")).toEqual([{ type: "add", text: "x" }]);
    expect(lineDiff("x", "")).toEqual([{ type: "del", text: "x" }]);
    const big = (p: string) =>
      Array.from({ length: 2100 }, (_, i) => `${p}${i}`).join("\n");
    expect(lineDiff(big("a"), big("b"))).toBeNull();
  });
});
