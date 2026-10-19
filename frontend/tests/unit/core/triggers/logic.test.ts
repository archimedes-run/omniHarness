import { describe, expect, it } from "vitest";

import {
  ACTIVITY_LABEL,
  OUTCOME_LABEL,
  timestamp,
} from "@/core/triggers/logic";

describe("triggers surface logic", () => {
  it("keeps the three rule conditions apart (FR-017)", () => {
    expect(new Set(Object.values(ACTIVITY_LABEL)).size).toBe(3);
  });
  it("gives every outcome its own label (FR-018)", () => {
    expect(new Set(Object.values(OUTCOME_LABEL)).size).toBe(5);
  });
  it("renders a missing time as never or not recorded, never blank (FR-022)", () => {
    expect(timestamp(null, "never")).toBe("never");
    expect(timestamp(null, "not-recorded")).toBe("not recorded");
  });
});
