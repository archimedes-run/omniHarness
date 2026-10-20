import { describe, expect, it } from "vitest";

import {
  headline,
  idFromName,
  nextRunText,
  quietHoursText,
  runWords,
  shortSchedule,
  when,
} from "@/core/automations/wording";
import type { RunView } from "@/core/triggers/types";

const NY = "America/New_York";
// Tuesday 2026-10-20, 10:00 in New York.
const NOW = new Date("2026-10-20T14:00:00Z");

const cron = (schedule: string, timezone = NY) => ({
  type: "cron",
  match: { schedule, timezone },
  destination: "remote",
});

const run = (patch: Partial<RunView>): RunView => ({
  event_id: "e",
  at: "2026-10-20T08:45:00-04:00",
  kind: "delivered",
  settled_at: "2026-10-20T12:46:00+00:00",
  reason: "",
  held_because: null,
  held_reason: "",
  delivered_with: [],
  batch_not_recorded: false,
  thread_id: null,
  ...patch,
});

describe("schedule wording", () => {
  it("says the board's short and long forms", () => {
    expect(shortSchedule(cron("45 8 * * 1-5"))).toBe("Weekdays 8:45 AM");
    expect(shortSchedule(cron("0 16 * * 5"))).toBe("Fridays 4:00 PM");
    expect(headline(cron("45 8 * * 1-5"))).toBe(
      "Weekdays at 8:45 AM · America/New_York · to Telegram",
    );
    expect(
      shortSchedule({ type: "watcher", match: { event: "waiting-on-user" } }),
    ).toBe("When a session waits on you");
  });

  it("names the engine's default zone for a rule that names none", () => {
    expect(
      headline({
        type: "cron",
        match: { schedule: "0 9 * * *" },
        destination: "auto",
        timezone: NY,
      }),
    ).toMatch(/^Every day at 9:00 AM · America\/New_York · /);
  });

  it("shows a schedule it cannot simplify as cron, never rewritten", () => {
    expect(shortSchedule(cron("*/15 * * * *"))).toBe("Cron */15 * * * *");
  });
});

describe("next run", () => {
  it("is the server's instant, said in the rule's zone", () => {
    const rule = {
      next_run: "scheduled" as const,
      next_run_at: "2026-10-21T08:45:00-04:00",
      match: { timezone: NY },
    };
    expect(nextRunText(rule, NOW)).toBe("Tomorrow 8:45 AM");
  });

  it("says when a run held for quiet hours will actually be delivered", () => {
    const rule = {
      next_run: "scheduled" as const,
      next_run_at: "2026-10-21T05:30:00-04:00",
      deliver_at: "2026-10-21T07:00:00-04:00",
      held_for_quiet_hours: true,
      match: { timezone: NY },
    };
    expect(nextRunText(rule, NOW)).toBe(
      "Tomorrow 7:00 AM (due 5:30 AM, held for quiet hours)",
    );
  });

  it("shows a rule without a zone in the user's zone", () => {
    const rule = {
      next_run: "scheduled" as const,
      next_run_at: "2026-10-21T09:00:00+00:00",
      match: {},
      timezone: NY,
    };
    expect(nextRunText(rule, NOW)).toBe("Tomorrow 5:00 AM");
  });

  it("says why there is no time instead of guessing one", () => {
    const m = { match: {} };
    expect(nextRunText({ ...m, next_run: "off" }, NOW)).toBe("None: it is off");
    expect(nextRunText({ ...m, next_run: "engine-off" }, NOW)).toMatch(
      /engine is off/,
    );
    expect(nextRunText({ ...m, next_run: "on-event" }, NOW)).toBe(
      "When it happens",
    );
    expect(nextRunText({ ...m, next_run: "cant-tell" }, NOW)).toBe(
      "Can't tell yet",
    );
    expect(nextRunText({ ...m, next_run: "scheduled" }, NOW)).toBe(
      "Can't tell yet",
    );
  });

  it("names the day relative to the rule's zone, not the browser's", () => {
    // 02:00 UTC on the 21st is still the 20th in New York.
    expect(when("2026-10-21T02:00:00Z", NY, NOW)).toBe("Today 10:00 PM");
    expect(when("2026-10-23T12:45:00Z", NY, NOW)).toBe("Fri 8:45 AM");
    expect(when("2026-11-03T13:45:00Z", NY, NOW)).toBe("Nov 3, 8:45 AM");
  });
});

describe("quiet hours", () => {
  it("reads as a span, off, or can't tell", () => {
    const q = { enabled: true, start: "22:00", end: "07:00", timezone: NY };
    expect(quietHoursText(q, NY)).toBe("10 PM to 7 AM");
    expect(quietHoursText({ ...q, end: "07:30" }, "UTC")).toBe(
      "10 PM to 7:30 AM (America/New_York)",
    );
    expect(quietHoursText({ ...q, enabled: false }, NY)).toBe("Off");
    expect(quietHoursText(null, NY)).toBe("Can't tell yet");
  });
});

describe("run history wording", () => {
  it("says each outcome as the board does", () => {
    expect(runWords(run({}), NY).label).toBe("Delivered");
    const held = runWords(
      run({
        kind: "held-then-delivered",
        held_because: "mid-conversation",
        settled_at: "2026-10-16T13:02:00Z",
      }),
      NY,
    );
    expect(held.label + held.detail).toBe(
      "Held, then delivered at 9:02 AM. You were mid-conversation.",
    );
    const batched = runWords(
      run({
        kind: "delivered-with-others",
        delivered_with: [{ rule_id: "blocked-session", event_id: "s" }],
      }),
      NY,
      () => "Blocked session alert",
    );
    expect(batched.label + batched.detail).toBe(
      "Delivered with 1 other (Blocked session alert), one message",
    );
    const failed = runWords(
      run({ kind: "failed", reason: "gave up after 3 attempts: timeout" }),
      NY,
    );
    expect(failed.label + failed.detail).toBe(
      "Failed: gave up after 3 attempts: timeout",
    );
  });

  it("never calls an unsettled or unknown run delivered", () => {
    expect(runWords(run({ kind: "pending" }), NY).label).toBe("Can't tell yet");
    expect(runWords(run({ kind: "cant-tell" }), NY).label).toBe(
      "Can't tell yet",
    );
  });
});

describe("a new automation's id", () => {
  it("comes from its name and never collides", () => {
    expect(idFromName("Standup nudge!", [])).toBe("standup-nudge");
    expect(idFromName("Standup nudge", ["standup-nudge"])).toBe(
      "standup-nudge-2",
    );
    expect(idFromName("  ", [])).toBe("automation");
  });
});
