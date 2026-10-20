import { describe, expect, it } from "vitest";

import {
  ago,
  alertKey,
  dateLine,
  dayLabel,
  dueLabel,
  greeting,
  knownBy,
  needsYou,
  sessionStatus,
  sortTime,
  startOfDay,
  taskProgress,
  whenLabel,
} from "@/core/home/logic";
import { countsTowardBadge } from "@/core/inbox/hooks";
import { STATE_LABEL } from "@/core/sessions/logic";

// Local times: the helpers speak in the viewer's own zone.
const at = (h: number, m = 0, day = 19) => new Date(2026, 9, day, h, m);

describe("the greeting", () => {
  it("follows the time of day", () => {
    expect(greeting(at(8), "Rishabh")).toBe("Good morning, Rishabh");
    expect(greeting(at(13), "Rishabh")).toBe("Good afternoon, Rishabh");
    expect(greeting(at(19), "Rishabh")).toBe("Good evening, Rishabh");
    expect(greeting(at(2), "Rishabh")).toBe("Good evening, Rishabh");
  });

  it("has no name while the name cannot be told", () => {
    expect(greeting(at(19), undefined)).toBe("Good evening");
    expect(greeting(at(19), "  ")).toBe("Good evening");
  });

  it("says the date in words", () => {
    expect(dateLine(at(19))).toBe("Monday, October 19");
  });
});

describe("what needs you", () => {
  it("adds what it can read", () => {
    expect(needsYou([1, 1, 0])).toBe("2 things need you");
    expect(needsYou([1, 0, 0])).toBe("1 thing needs you");
    expect(needsYou([0, 0, 0])).toBe("Nothing needs you");
  });

  it("never reads an unreadable source as zero", () => {
    expect(needsYou([0, null, 0])).toBe("Can't tell yet what needs you");
    expect(needsYou([2, undefined, 0])).toBe("At least 2 things need you");
  });
});

describe("times", () => {
  it("says how long ago", () => {
    const now = at(19, 30);
    expect(ago(new Date(now.getTime() - 12_000).toISOString(), now)).toBe(
      "12s ago",
    );
    expect(ago(new Date(now.getTime() - 6 * 60_000).toISOString(), now)).toBe(
      "6 min ago",
    );
    expect(ago(null, now)).toBeNull();
    expect(ago("not a time", now)).toBeNull();
  });

  it("starts the day at local midnight", () => {
    expect(startOfDay(at(19, 30)).getHours()).toBe(0);
    expect(startOfDay(at(19, 30)).getDate()).toBe(19);
  });

  it("names when an upcoming run is", () => {
    const now = at(10); // Monday
    expect(whenLabel(at(16).toISOString(), now)).toBe("Today 4:00 PM");
    expect(whenLabel(at(8, 45, 20).toISOString(), now)).toBe(
      "Tomorrow 8:45 AM",
    );
    expect(whenLabel(at(17, 0, 23).toISOString(), now)).toBe("Fri 5:00 PM");
    expect(whenLabel(at(17, 0, 30).toISOString(), now)).toBe("Oct 30 5:00 PM");
  });

  it("names an all-day calendar date as a day, and sorts it at its midnight", () => {
    const now = at(10);
    expect(dayLabel("2026-10-19", now)).toBe("Today");
    expect(dayLabel("2026-10-20", now)).toBe("Tomorrow");
    expect(dayLabel("2026-10-23", now)).toBe("Fri");
    expect(dayLabel("2026-10-30", now)).toBe("Oct 30");
    expect(sortTime("2026-10-20", true)).toBe(at(0, 0, 20).getTime());
  });

  it("reads a due date as that local day", () => {
    expect(dueLabel("2026-10-23")).toBe("Due Fri, Oct 23");
  });
});

describe("projects", () => {
  it("counts done of all tasks, and says when there is no task list", () => {
    expect(taskProgress({ open_tasks: 4, done_tasks: 3 })).toEqual({
      label: "3 of 7 tasks",
      percent: 43,
    });
    expect(taskProgress({ open_tasks: 0, done_tasks: 0 })).toBeNull();
  });
});

describe("sessions", () => {
  const now = at(19, 30);
  it("uses the sessions page's words", () => {
    expect(
      sessionStatus(
        { display_state: "working", last_activity_at: null },
        STATE_LABEL,
        now,
      ),
    ).toEqual({ text: "Working", tone: "good" });
    expect(
      sessionStatus(
        { display_state: "waiting-on-user", last_activity_at: null },
        STATE_LABEL,
        now,
      ),
    ).toEqual({ text: STATE_LABEL["waiting-on-user"], tone: "warn" });
    expect(
      sessionStatus(
        {
          display_state: "completed",
          last_activity_at: new Date(now.getTime() - 22 * 60_000).toISOString(),
        },
        STATE_LABEL,
        now,
      ).text,
    ).toBe("Finished 22 min ago");
  });

  it("says how a state is known", () => {
    expect(knownBy("observed")).toBe("Observed");
    expect(knownBy("inferred")).toBe("Inferred");
    expect(knownBy("unknown")).toBe("Can't tell");
  });
});

describe("the badge", () => {
  const alert = {
    rule_id: "r",
    event_id: "e",
    event_type: "cron",
    at: "",
    reason: "",
    thread_id: null,
  };
  it("counts waiting and missed alerts, not dismissed or delivered ones", () => {
    expect(countsTowardBadge({ ...alert, state: "waiting" })).toBe(true);
    expect(countsTowardBadge({ ...alert, state: "not-delivered" })).toBe(true);
    expect(
      countsTowardBadge({ ...alert, state: "waiting", dismissed: true }),
    ).toBe(false);
    expect(countsTowardBadge({ ...alert, state: "delivered" })).toBe(false);
    expect(alertKey(alert)).toBe("r:e");
  });
});
