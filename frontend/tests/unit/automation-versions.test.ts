import { describe, expect, it } from "vitest";

import type { RuleVersion, RuleVersions } from "@/core/automations/api";
import {
  changedLine,
  deletedUndo,
  restoreError,
  sourceLabel,
  versionRows,
} from "@/core/automations/versions";

const v = (patch: Partial<RuleVersion> & { version: number }): RuleVersion => ({
  at: "2026-11-13T14:00:00Z",
  who: "user:1",
  source: "manual",
  via: "page",
  changed: ["prompt"],
  deleted: false,
  ...patch,
});

const data = (patch: Partial<RuleVersions>): RuleVersions => ({
  rule_id: "r",
  current: 1,
  unrecorded: false,
  exists: true,
  can_undo_create: false,
  versions: [],
  ...patch,
});

describe("source words", () => {
  it("names each surface and a hand edit", () => {
    expect(sourceLabel({ source: "manual", via: "page" })).toBe(
      "Edited on the Automations page",
    );
    expect(sourceLabel({ source: "manual", via: "studio" })).toBe(
      "Edited in Studio",
    );
    expect(sourceLabel({ source: "chat", via: "chat" })).toBe("Built in chat");
    expect(sourceLabel({ source: "undo", via: "studio" })).toBe(
      "Undone in Studio",
    );
    expect(sourceLabel({ source: "existing", via: "hand-edit" })).toBe(
      "Hand edit of the rules file",
    );
    expect(sourceLabel({ source: "existing", via: "" })).toBe(
      "As it was when history began",
    );
    expect(sourceLabel({ source: "manual", via: "agent-deleted" })).toBe(
      "Switched off: its agent was deleted",
    );
  });
});

describe("what changed, in one line", () => {
  it("words fields, creates and deletes, and caps the list", () => {
    expect(changedLine(v({ version: 1, changed: ["created"] }))).toBe(
      "Created",
    );
    expect(
      changedLine(v({ version: 2, deleted: true, changed: ["deleted"] })),
    ).toBe("Deleted");
    expect(
      changedLine(v({ version: 2, changed: ["match.schedule", "prompt"] })),
    ).toBe("Changed schedule, what it asks");
    expect(
      changedLine(
        v({
          version: 2,
          changed: ["a", "b", "enabled", "destination", "name"],
        }),
      ),
    ).toBe("Changed a, b, on/off +2 more");
    expect(
      changedLine(v({ version: 1, source: "existing", changed: [] })),
    ).toBe("The rule as it already was");
  });
});

describe("rows and their actions", () => {
  it("offers Undo on the latest change and Restore on older ones", () => {
    const rows = versionRows(
      data({
        current: 3,
        versions: [
          v({ version: 3 }),
          v({ version: 2 }),
          v({ version: 1, source: "existing", via: "", changed: [] }),
        ],
      }),
      "UTC",
    );
    expect(rows.map((r) => [r.label, r.current, r.action])).toEqual([
      ["v3", true, { kind: "undo", toVersion: 2 }],
      ["v2", false, { kind: "restore", toVersion: 2 }],
      ["v1", false, { kind: "restore", toVersion: 1 }],
    ]);
    expect(rows[0]!.at).toBe("Nov 13, 2026, 2:00 PM");
  });

  it("undo of a create goes to version 0 (deletes); a baseline-only rule has no undo", () => {
    const created = versionRows(
      data({
        can_undo_create: true,
        versions: [v({ version: 1, changed: ["created"] })],
      }),
    );
    expect(created[0]!.action).toEqual({ kind: "undo", toVersion: 0 });
    const baseline = versionRows(
      data({ versions: [v({ version: 1, source: "existing", via: "" })] }),
    );
    expect(baseline[0]!.action).toBeNull();
  });

  it("a hand edit not yet recorded is the latest change, and Undo goes back past it", () => {
    const rows = versionRows(
      data({
        current: 3,
        unrecorded: true,
        versions: [v({ version: 2 }), v({ version: 1 })],
      }),
    );
    expect(rows[0]).toMatchObject({
      key: "unrecorded",
      source: "Hand edit of the rules file",
      current: true,
      action: { kind: "undo", toVersion: 2 },
    });
    expect(rows[1]!.action).toEqual({ kind: "restore", toVersion: 2 });
    expect(rows[1]!.current).toBe(false);
  });

  it("an older deleted version offers no restore", () => {
    const rows = versionRows(
      data({
        current: 3,
        versions: [
          v({ version: 3, changed: ["created"] }),
          v({ version: 2, deleted: true, changed: ["deleted"] }),
          v({ version: 1, changed: ["created"] }),
        ],
      }),
    );
    expect(rows[1]!.action).toBeNull();
  });
});

describe("the deleted state", () => {
  it("offers Undo back to the version before the delete", () => {
    expect(
      deletedUndo(
        data({
          exists: false,
          current: 2,
          versions: [
            v({ version: 2, deleted: true, changed: ["deleted"] }),
            v({ version: 1, changed: ["created"] }),
          ],
        }),
      ),
    ).toEqual({ kind: "undo", toVersion: 1 });
  });

  it("is absent while the rule exists or with nothing to bring back", () => {
    expect(deletedUndo(data({ versions: [v({ version: 1 })] }))).toBeNull();
    expect(
      deletedUndo(
        data({
          exists: false,
          versions: [v({ version: 1, deleted: true })],
        }),
      ),
    ).toBeNull();
  });
});

describe("a refused restore", () => {
  it("says a stale one plainly", () => {
    expect(restoreError(409, "x")).toMatch(/changed since/);
    expect(restoreError(422, "bad schedule")).toBe(
      "Not restored: bad schedule",
    );
  });
});
