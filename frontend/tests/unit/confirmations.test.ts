import { describe, expect, it } from "vitest";

import {
  canConfirm,
  canDecline,
  formatRemaining,
  isExpired,
  msRemaining,
  requiresTypedCount,
} from "@/core/confirmations/logic";
import type { PendingAction } from "@/core/confirmations/types";

const NOW = new Date("2026-09-23T12:00:00Z");

function action(overrides: Partial<PendingAction> = {}): PendingAction {
  return {
    id: "abc123abc123",
    tool_name: "calendar_decline",
    plan_text: "I will decline 2 meetings",
    targets: ["Standup", "Review"],
    requester: "lead_agent",
    delegation_chain: [],
    expires_at: "2026-09-23T16:00:00Z",
    thread_id: "t1",
    threshold_targets: 10,
    requires_typed_count: false,
    ...overrides,
  };
}

describe("expiry is driven by the clock, not the fetch", () => {
  it("counts down while the action is live", () => {
    expect(msRemaining(action().expires_at, NOW)).toBe(4 * 60 * 60 * 1000);
    expect(isExpired(action(), NOW)).toBe(false);
  });

  it("becomes expired the moment the deadline passes, with no refetch", () => {
    const justLapsed = new Date("2026-09-23T16:00:01Z");
    expect(isExpired(action(), justLapsed)).toBe(true);
  });

  it("treats the exact deadline as expired rather than as still open", () => {
    expect(isExpired(action(), new Date("2026-09-23T16:00:00Z"))).toBe(true);
  });

  it("says 'expired' rather than a negative duration", () => {
    expect(
      formatRemaining(action().expires_at, new Date("2026-09-23T17:00:00Z")),
    ).toBe("expired");
  });

  it.each([
    ["2026-09-23T12:00:00Z", "4h 0m left"],
    ["2026-09-23T15:30:00Z", "30m left"],
    ["2026-09-23T15:59:30Z", "30s left"],
  ])("formats the remaining time at %s", (at, expected) => {
    expect(formatRemaining(action().expires_at, new Date(at))).toBe(expected);
  });
});

describe("the scope threshold", () => {
  it("does not ask for a count below the threshold", () => {
    expect(requiresTypedCount(action())).toBe(false);
    expect(canConfirm(action(), "", NOW)).toBe(true);
  });

  it("asks for a count above it", () => {
    const big = action({
      targets: Array.from({ length: 12 }, (_, i) => `m${i}`),
    });
    expect(requiresTypedCount(big)).toBe(true);
    expect(canConfirm(big, "", NOW)).toBe(false);
  });

  it("accepts only the correct count", () => {
    const big = action({
      targets: Array.from({ length: 12 }, (_, i) => `m${i}`),
    });
    expect(canConfirm(big, "12", NOW)).toBe(true);
    expect(canConfirm(big, " 12 ", NOW)).toBe(true);
    for (const wrong of ["11", "13", "120", "", "twelve"]) {
      expect(canConfirm(big, wrong, NOW), `"${wrong}" was accepted`).toBe(
        false,
      );
    }
  });

  it("blocks confirming an expired action however the count is typed", () => {
    const big = action({
      targets: Array.from({ length: 12 }, (_, i) => `m${i}`),
    });
    expect(canConfirm(big, "12", new Date("2026-09-23T17:00:00Z"))).toBe(false);
  });
});

describe("declining", () => {
  it("is never gated by the threshold", () => {
    // Proof of reading is required to ACT, not to refuse. A decline that is
    // harder than a confirmation pushes a hesitant user toward the dangerous
    // answer, which is the opposite of what the gate is for.
    const big = action({
      targets: Array.from({ length: 50 }, (_, i) => `m${i}`),
    });
    expect(canConfirm(big, "", NOW)).toBe(false);
    expect(canDecline(big, NOW)).toBe(true);
  });

  it("is unavailable once the action has expired", () => {
    expect(canDecline(action(), new Date("2026-09-23T17:00:00Z"))).toBe(false);
  });
});
