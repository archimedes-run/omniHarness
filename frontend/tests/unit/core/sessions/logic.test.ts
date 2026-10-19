import { describe, expect, it } from "vitest";

import { STATE_LABEL, watcherHealth } from "@/core/sessions/logic";
import type { SessionsView } from "@/core/sessions/types";

const base: SessionsView = {
  reachable: true,
  unreachable_kind: null,
  unreachable_detail: null,
  observability: "live",
  staleness_seconds: 3,
  as_of: null,
  sessions: [],
  observe_only: true,
  observe_only_reason: "",
};

describe("watcher health (FR-013)", () => {
  it("never reports an unreachable watcher as a state of the watcher", () => {
    expect(
      watcherHealth({
        ...base,
        reachable: false,
        unreachable_kind: "unreachable",
        observability: null,
        sessions: null,
      }).kind,
    ).toBe("cannot-see");
  });
  it("says how stale stale is", () => {
    expect(
      watcherHealth({
        ...base,
        observability: "stale",
        staleness_seconds: 7200,
      }),
    ).toEqual({ kind: "stale", age: "2 h" });
  });
  it("keeps never-observed apart from live", () => {
    expect(
      watcherHealth({ ...base, observability: "never-observed" }).kind,
    ).toBe("never-observed");
  });
});

describe("state labels (FR-011, FR-012)", () => {
  it("does not collapse completed and stalled", () => {
    expect(STATE_LABEL.completed).not.toBe(STATE_LABEL.stalled);
  });
  it("hedges the inferred states", () => {
    expect(STATE_LABEL["waiting-on-user"]).toMatch(/looks like/i);
    expect(STATE_LABEL.stalled).toMatch(/may/i);
  });
});
