import { describe, expect, it } from "vitest";

import {
  PASTE_MIN_CHARS,
  PASTE_MIN_LINES,
  isLongMessage,
  pastePreview,
  pasteSize,
  shouldCollapsePaste,
  splitPastedText,
  wrapPastes,
} from "@/core/messages/pasted-text";

describe("pasted text", () => {
  it("collapses only long pastes", () => {
    expect(shouldCollapsePaste("short")).toBe(false);
    expect(shouldCollapsePaste("x".repeat(PASTE_MIN_CHARS - 1))).toBe(false);
    expect(shouldCollapsePaste("x".repeat(PASTE_MIN_CHARS))).toBe(true);
    expect(shouldCollapsePaste("a\n".repeat(PASTE_MIN_LINES))).toBe(true);
  });

  it("leaves a paste that contains the markers alone", () => {
    const long = "x".repeat(PASTE_MIN_CHARS);
    expect(shouldCollapsePaste(`${long}</pasted_text>`)).toBe(false);
    expect(shouldCollapsePaste(`<pasted_text>${long}`)).toBe(false);
  });

  it("round-trips typed text and several pastes", () => {
    const a = "first paste\n\nwith two paragraphs";
    const b = "second <b>paste</b> with `code`";
    const sent = wrapPastes("  look at these  ", [a, b]);
    expect(splitPastedText(sent)).toEqual({
      text: "look at these",
      pastes: [a, b],
    });
  });

  it("sends a paste on its own when nothing was typed", () => {
    const sent = wrapPastes("", ["only this"]);
    expect(sent.startsWith("<pasted_text>")).toBe(true);
    expect(splitPastedText(sent)).toEqual({ text: "", pastes: ["only this"] });
  });

  it("returns a message without blocks unchanged", () => {
    expect(splitPastedText("plain  message\n\n\nkept")).toEqual({
      text: "plain  message\n\n\nkept",
      pastes: [],
    });
  });

  it("labels a card with its first words on one line", () => {
    expect(pastePreview("Startup   Research:\n\nCan we build")).toBe(
      "Startup Research: Can we build",
    );
    expect(pastePreview("word ".repeat(100), 20)).toBe("word word word word…");
    expect(pasteSize("one two\nthree")).toBe("3 words · 2 lines");
  });

  it("folds a message past two paragraphs or 600 characters", () => {
    expect(isLongMessage("one\n\ntwo")).toBe(false);
    expect(isLongMessage("one\n\ntwo\n\nthree")).toBe(true);
    expect(isLongMessage("x".repeat(601))).toBe(true);
  });
});
