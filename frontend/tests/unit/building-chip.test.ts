import { readFileSync } from "node:fs";
import { join } from "node:path";

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { BuildingChipView } from "@/components/workspace/chat-bar/building-chip";

/**
 * The "Building: <name>" chip above the chat bar (Spec 010 FR-003): its
 * words, its × (a real button with a name that says what it does), and its
 * colours (Graphite tokens; never muted text on the primary-subtle fill,
 * which fails AA in dark). Contrast is measured in both themes by
 * tests/rendering/building-chip.spec.ts.
 */
const render = (saved: number | null = null) =>
  renderToStaticMarkup(
    createElement(BuildingChipView, {
      building: {
        kind: "agent",
        name: "inbox-triage",
        title: "Inbox triage",
        draft_id: "d-1",
        saved_version: saved,
      },
      onDrop: () => undefined,
    }),
  );

describe("the Building chip", () => {
  it("names what is being built, and a status role announces it", () => {
    const html = render();
    expect(html).toContain('role="status"');
    expect(html.replace(/<[^>]+>/g, "")).toContain("Building: Inbox triage");
    expect(html).not.toContain("saved as version");
  });

  it("says when the build was saved, and keeps the chip", () => {
    expect(render(3).replace(/<[^>]+>/g, "")).toContain(
      "Building: Inbox triage · saved as version 3",
    );
  });

  it("drops the draft with a named button", () => {
    const html = render();
    expect(html).toMatch(
      /<button[^>]*aria-label="Stop building Inbox triage and drop the draft"/,
    );
    expect(html).toContain('type="button"');
  });

  it("uses the Graphite tokens, and no muted text on its fill", () => {
    const source = readFileSync(
      join(
        __dirname,
        "..",
        "..",
        "src",
        "components",
        "workspace",
        "chat-bar",
        "building-chip.tsx",
      ),
      "utf-8",
    );
    expect(source).toContain("bg-primary-subtle");
    expect(source).not.toMatch(/text-muted-foreground/);
    expect(source).not.toMatch(/#[0-9a-fA-F]{3,6}\b|rgb\(/);
  });
});
