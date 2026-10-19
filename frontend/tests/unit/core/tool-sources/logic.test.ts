import { describe, expect, it } from "vitest";

import { describeState } from "@/core/tool-sources/logic";
import type { ToolSource } from "@/core/tool-sources/types";

function source(
  state: ToolSource["state"],
  extra: Partial<ToolSource> = {},
): ToolSource {
  return {
    id: "local:x",
    name: "x",
    kind: "local",
    state,
    tool_count: null,
    error: null,
    selected: null,
    ...extra,
  };
}

describe("tool source states are distinct (FR-040)", () => {
  // Phase 2.5: Settings → Connections names four statuses — Not configured,
  // Off, Unreachable, Live — for both kinds, shown in separate sections. So a
  // label is distinct within its kind, and every state's meaning is distinct.
  it("gives every state of a kind its own label", () => {
    const local: ToolSource["state"][] = [
      "live",
      "unreachable",
      "disabled",
      "not-configured",
      "not-loaded",
    ];
    const connector: ToolSource["state"][] = [
      "authorised",
      "authorised-selected",
      "authorised-not-selected",
      "not-authorised",
    ];
    for (const states of [local, connector]) {
      const labels = states.map((s) => describeState(source(s)).label);
      expect(new Set(labels).size, labels.join(" | ")).toBe(states.length);
    }
    const all = [...local, ...connector];
    const meanings = all.map((s) => describeState(source(s)).meaning);
    expect(new Set(meanings).size).toBe(all.length);
  });

  it("uses the four Connections statuses", () => {
    expect(describeState(source("live")).label).toBe("Live");
    expect(describeState(source("disabled")).label).toBe("Off");
    expect(describeState(source("unreachable")).label).toBe("Unreachable");
    expect(describeState(source("not-configured")).label).toBe(
      "Not configured",
    );
    expect(describeState(source("authorised")).label).toBe("Live");
    expect(describeState(source("not-authorised")).label).toBe(
      "Not configured",
    );
  });

  it("marks only a failing source as a problem", () => {
    expect(describeState(source("unreachable")).tone).toBe("problem");
    expect(describeState(source("not-configured")).tone).not.toBe("problem");
  });

  it("does not tell an authorised connector to authorise again (SC-024)", () => {
    expect(describeState(source("authorised-not-selected")).meaning).toContain(
      "no need to authorise",
    );
  });
});
