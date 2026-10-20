import { describe, expect, it } from "vitest";

import {
  describeSchedule,
  fromCron,
  toCron,
} from "@/core/automations/schedule";

describe("the schedule form round-trips what it can show", () => {
  it("reads and writes the morning brief", () => {
    expect(fromCron("45 8 * * 1-5")).toEqual({
      time: "08:45",
      days: [1, 2, 3, 4, 5],
    });
    expect(toCron({ time: "08:45", days: [1, 2, 3, 4, 5] })).toBe(
      "45 8 * * 1-5",
    );
  });

  it("handles every day, lists, and 7 as Sunday", () => {
    expect(fromCron("0 16 * * *")?.days).toEqual([0, 1, 2, 3, 4, 5, 6]);
    expect(fromCron("0 9 * * 1,3,5")?.days).toEqual([1, 3, 5]);
    expect(fromCron("0 9 * * 6-7")?.days).toEqual([0, 6]);
    expect(toCron({ time: "16:00", days: [0, 1, 2, 3, 4, 5, 6] })).toBe(
      "0 16 * * *",
    );
    expect(toCron({ time: "09:05", days: [5, 1, 3] })).toBe("5 9 * * 1,3,5");
  });

  it("refuses shapes it cannot show, rather than rewriting them", () => {
    for (const expr of [
      "*/15 * * * *",
      "0 9 1 * *",
      "0 9 * 1 *",
      "0 9-17 * * *",
      "61 9 * * *",
      "0 9 * * MON",
      "0 9 * *",
    ]) {
      expect(fromCron(expr), expr).toBeNull();
    }
  });

  it("describes a schedule in words, and a raw one as raw", () => {
    expect(describeSchedule("45 8 * * 1-5", "America/New_York")).toBe(
      "Weekdays at 08:45 (America/New_York)",
    );
    expect(describeSchedule("0 10 * * 0,6")).toBe(
      "Weekends at 10:00 (America/New_York)",
    );
    expect(describeSchedule("*/15 * * * *", "UTC")).toBe(
      'Cron "*/15 * * * *" (UTC)',
    );
  });
});
