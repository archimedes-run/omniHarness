/**
 * The chat list's "updated" time, in a timezone behind UTC.
 *
 * The backend writes UTC; SQLite hands it back without a zone, and a zone-less
 * ISO string is parsed as LOCAL time. In New York (UTC-4 in October) a chat
 * updated a moment ago read "in about 4 hours". This file runs in New York:
 * the TZ is set before any Date is made, and the first test proves it took.
 */
process.env.TZ = "America/New_York";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { formatTimeAgo, parseTimestamp } from "@/core/utils/datetime";

const NOW = new Date("2026-10-19T16:00:10.000Z");

describe("formatTimeAgo in America/New_York", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
  });
  afterEach(() => vi.useRealTimers());

  it("really runs in New York", () => {
    // 240 minutes behind UTC on this date (EDT). Without this the rest proves nothing.
    expect(NOW.getTimezoneOffset()).toBe(240);
  });

  it("a zone-less UTC timestamp from just now reads as just now, not hours ahead", () => {
    const text = formatTimeAgo("2026-10-19T16:00:00.123456", "en-US");
    expect(text).toBe("less than a minute ago");
    expect(text).not.toMatch(/^in /);
  });

  it("the space-separated SQL shape is UTC too", () => {
    expect(formatTimeAgo("2026-10-19 16:00:00", "en-US")).toBe(
      "less than a minute ago",
    );
  });

  it("a timestamp with its zone is read as given", () => {
    expect(formatTimeAgo("2026-10-19T16:00:00+00:00", "en-US")).toBe(
      "less than a minute ago",
    );
    expect(formatTimeAgo("2026-10-19T12:00:00-04:00", "en-US")).toBe(
      "less than a minute ago",
    );
    expect(formatTimeAgo("2026-10-19T14:00:00Z", "en-US")).toBe(
      "about 2 hours ago",
    );
  });

  it("dates and epoch numbers pass through", () => {
    expect(parseTimestamp(NOW)).toBe(NOW);
    expect(parseTimestamp(NOW.getTime()).getTime()).toBe(NOW.getTime());
    // A date with no time is not a date-time: left to Date (which reads it as UTC).
    expect(parseTimestamp("2026-10-19").toISOString()).toBe(
      "2026-10-19T00:00:00.000Z",
    );
  });
});
