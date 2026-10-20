import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import {
  AVATAR_PALETTE_SIZE,
  LEAD_AGENT_ID,
  avatarClasses,
  avatarColor,
  avatarInitials,
  mentionClasses,
} from "@/core/agents/avatar";

const CSS = readFileSync(
  join(__dirname, "..", "..", "..", "src", "styles", "globals.css"),
  "utf8",
);

describe("avatar colours", () => {
  it("are stable: the same id always gets the same colour", () => {
    // Pinned values: a change to the hash would recolour every agent for
    // every user, so it must be a deliberate edit here.
    expect(avatarColor("researcher")).toBe(avatarColor("researcher"));
    expect(avatarColor("Researcher")).toBe(avatarColor("researcher"));
    expect(
      ["researcher", "coder", "release-manager", "writer"].map(avatarColor),
    ).toMatchInlineSnapshot(`
      [
        3,
        2,
        0,
        2,
      ]
    `);
  });

  it("give the lead agent its own fixed colour", () => {
    expect(avatarColor(LEAD_AGENT_ID)).toBe("lead");
    expect(avatarColor("lead")).toBe("lead");
    expect(avatarClasses(LEAD_AGENT_ID)).toContain("bg-avatar-lead");
  });

  it("spread agents over the whole palette, never the lead colour", () => {
    const seen = new Set(
      Array.from({ length: 200 }, (_, i) => avatarColor(`agent-${i}`)),
    );
    expect(seen.has("lead")).toBe(false);
    expect(seen.size).toBe(AVATAR_PALETTE_SIZE);
  });

  it("colour a mention like the mentioned agent's avatar", () => {
    const n = avatarColor("coder");
    expect(avatarClasses("coder")).toContain(`bg-avatar-${n} `);
    expect(mentionClasses("coder")).toBe(`text-avatar-${n}-foreground`);
  });

  it("name only colours the theme defines, in both themes", () => {
    for (const n of ["lead", ...Array.from({ length: 8 }, (_, i) => i)]) {
      const fill = new RegExp(`--avatar-${n}:`, "g");
      const fg = new RegExp(`--avatar-${n}-foreground:`, "g");
      expect(CSS.match(fill)?.length, `--avatar-${n}`).toBe(2);
      expect(CSS.match(fg)?.length, `--avatar-${n}-foreground`).toBe(2);
    }
  });

  it("always have initials, so colour is never the only identifier", () => {
    expect(avatarInitials("Release manager")).toBe("RM");
    expect(avatarInitials("release_manager")).toBe("RM");
    expect(avatarInitials("coder")).toBe("CO");
    expect(avatarInitials("  ")).toBe("?");
  });
});
