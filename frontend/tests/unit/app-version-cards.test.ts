import { describe, expect, it } from "vitest";

import {
  anchorCards,
  cardWords,
  clipDescription,
  clipWords,
  orderCards,
} from "@/core/apps/version-cards";

/** App cards in a chat: clipping, placement, order and words per state. */

const card = (over: Record<string, unknown> = {}) => ({
  id: "c3",
  app_id: "today",
  app_name: "Today",
  version: 3,
  kind: "version" as const,
  status: "pending" as const,
  keeps_version: 2,
  resolved_at: null,
  created_at: "2026-11-14T10:03:00Z",
  ...over,
});

describe("clipWords", () => {
  it("cuts at a word boundary with an ellipsis, never mid-word", () => {
    expect(clipWords("short text")).toBe("short text");
    const long =
      "Adds a calendar tile; enforces the 360 px layout; " + "word ".repeat(60);
    const out = clipWords(long, 60);
    expect(out.endsWith("…")).toBe(true);
    expect(out.length).toBeLessThanOrEqual(61);
    expect(long.startsWith(out.slice(0, -1))).toBe(true);
    expect(out).not.toMatch(/[;,]…$/);
    expect(clipWords("x; enforcing everything carefully", 12)).toBe(
      "x; enforcing…",
    );
  });
});

describe("anchorCards", () => {
  it("finds the turn that registered each version, by card id or by version", () => {
    const texts = [
      "build me a Today page",
      "- App registered by the system: id today, version 2; it needs approval",
      "ok",
      "- App registered by the system: id today, version 3 (card c3); offered",
      "- App registered by the system: id today, version 30; offered",
    ];
    const a = anchorCards(texts, [
      { id: "c2", app_id: "today", version: 2 },
      { id: "c3", app_id: "today", version: 3 },
      { id: "c9", app_id: "today", version: 9 },
    ]);
    expect(a.get("c2")).toBe(1);
    expect(a.get("c3")).toBe(3);
    expect(a.has("c9")).toBe(false);
  });
});

describe("orderCards", () => {
  it("orders oldest first and knows the next version and the newest pending", () => {
    const { cards, newer, newestPending } = orderCards([
      card({ id: "c4", version: 4, created_at: "2026-11-14T10:04:00Z" }),
      card({
        id: "c2",
        version: 2,
        status: "superseded",
        created_at: "2026-11-14T10:02:00Z",
      }),
      card({ id: "c3", version: 3, created_at: "2026-11-14T10:03:00Z" }),
    ]);
    expect(cards.map((c) => c.version)).toEqual([2, 3, 4]);
    expect(newer.get("c2")).toBe(3);
    expect(newer.get("c3")).toBe(4);
    expect(newer.has("c4")).toBe(false);
    expect(newestPending).toBe("c4");
  });
});

describe("cardWords", () => {
  it("pending: names the version served now, and is open only when newest", () => {
    const w = cardWords(card(), 2, undefined, true);
    expect(w).toMatchObject({ state: "pending", open: true });
    expect(w.sentence).toBe("Version 2 keeps running until you choose.");
    expect(w.sameData).toContain("version 2, the version you use now");
    expect(cardWords(card(), 2, 4, false).open).toBe(false);
  });

  it("used: in use since, the old version in History; never the stale pending text", () => {
    const w = cardWords(
      card({ status: "approved", resolved_at: "2026-11-14T10:05:00Z" }),
      3,
      undefined,
      false,
    );
    expect(w.state).toBe("used");
    expect(w.open).toBe(false);
    expect(w.sentence).toMatch(/^In use since .+\. Version 2 is in History\.$/);
    expect(w.line).toMatch(/^Version 3 — in use since /);
    expect(w.sentence).not.toContain("keeps running");
  });

  it("used then replaced, or superseded: one line naming what replaced it", () => {
    expect(cardWords(card({ status: "approved" }), 4, 4, false).line).toBe(
      "Version 3 — replaced by version 4",
    );
    expect(cardWords(card({ status: "superseded" }), 2, 4, false).line).toBe(
      "Version 3 — replaced by version 4",
    );
  });

  it("kept", () => {
    const w = cardWords(card({ status: "kept" }), 2, undefined, false);
    expect(w).toMatchObject({
      state: "kept",
      line: "Kept version 2",
      sentence: "You kept version 2.",
    });
  });
});

describe("clipDescription", () => {
  it("drops the word the gateway cut at 300 characters", () => {
    const cut = ("word ".repeat(59) + "enforcing").slice(0, 300);
    expect(cut.endsWith("enfor")).toBe(true);
    const out = clipDescription(cut);
    expect(out.endsWith("…")).toBe(true);
    expect(out).not.toContain("enfor");
    expect(clipDescription("Short.")).toBe("Short.");
  });
});
