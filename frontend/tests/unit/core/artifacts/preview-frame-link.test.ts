import { expect, test } from "vitest";

import { previewFrameRefreshMs } from "@/core/artifacts/hooks";

const NOW = Date.parse("2026-11-15T12:00:00Z");

test("the live preview asks for a fresh frame link at half its remaining life", () => {
  // The gateway's 10 minutes: every 5 minutes, well before it lapses.
  expect(previewFrameRefreshMs("2026-11-15T12:10:00+00:00", NOW)).toBe(300_000);
  expect(previewFrameRefreshMs("2026-11-15T12:00:12Z", NOW)).toBe(6_000);
});

test("never more often than every 5 seconds, even for a lapsed or unreadable expiry", () => {
  expect(previewFrameRefreshMs("2026-11-15T12:00:02Z", NOW)).toBe(5_000);
  expect(previewFrameRefreshMs("2026-11-15T11:00:00Z", NOW)).toBe(5_000);
  expect(previewFrameRefreshMs("not a date", NOW)).toBe(5_000);
});
