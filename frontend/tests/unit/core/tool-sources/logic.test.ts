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
  it("gives every state its own label", () => {
    const states: ToolSource["state"][] = [
      "live",
      "unreachable",
      "disabled",
      "not-configured",
      "not-loaded",
      "authorised",
      "authorised-selected",
      "authorised-not-selected",
      "not-authorised",
    ];
    const labels = states.map((s) => describeState(source(s)).label);
    expect(new Set(labels).size).toBe(states.length);
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
