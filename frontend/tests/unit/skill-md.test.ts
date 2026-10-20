import { describe, expect, it } from "vitest";

import {
  composeSkillMd,
  parseSkillMd,
  skillSlug,
  supportPathFor,
} from "@/core/studio/skill-md";

/**
 * Skill Studio edits SKILL.md's description (the sentence the model reads to
 * pick the skill) and body, and must keep every other frontmatter line.
 */
describe("SKILL.md round trip", () => {
  const md = `---
name: status-format
description: "Use when reporting status: briefings and wrap-ups."
license: MIT
allowed-tools:
  - read_file
---

# Status

- Moved
`;

  it("reads the description, the body and keeps the rest", () => {
    const doc = parseSkillMd(md);
    expect(doc.name).toBe("status-format");
    expect(doc.description).toBe(
      "Use when reporting status: briefings and wrap-ups.",
    );
    expect(doc.body).toBe("# Status\n\n- Moved\n");
    expect(doc.rest).toEqual([
      "license: MIT",
      "allowed-tools:",
      "  - read_file",
    ]);
  });

  it("writes it back with the other lines intact and a quoted description", () => {
    const doc = parseSkillMd(md);
    const out = composeSkillMd({
      ...doc,
      description: 'Say "where are we": status',
    });
    expect(out).toContain('description: "Say \\"where are we\\": status"');
    expect(out).toContain("license: MIT\nallowed-tools:\n  - read_file\n---");
    expect(parseSkillMd(out).description).toBe('Say "where are we": status');
    expect(parseSkillMd(out).body).toBe("# Status\n\n- Moved\n");
  });

  it("reads a folded block description", () => {
    const doc = parseSkillMd(
      "---\nname: a\ndescription: >\n  first line\n  second line\n---\nbody\n",
    );
    expect(doc.description).toBe("first line second line");
    expect(doc.rest).toEqual([]);
  });
});

describe("names and paths", () => {
  it("slugs a title", () => {
    expect(skillSlug("Project status format!")).toBe("project-status-format");
  });
  it("puts each added file under a support folder", () => {
    expect(supportPathFor("score_risk.py")).toBe("scripts/score_risk.py");
    expect(supportPathFor("example-report.md")).toBe(
      "references/example-report.md",
    );
    expect(supportPathFor("logo.png")).toBe("assets/logo.png");
  });
});
