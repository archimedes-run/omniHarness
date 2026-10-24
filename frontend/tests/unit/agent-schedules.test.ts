import { describe, expect, it } from "vitest";

import { presetCron, presetOf } from "@/core/automations/schedule";
import { ruleDocOf, runsAs } from "@/core/automations/wording";
import type { RuleView } from "@/core/triggers/types";

/** Feature 006-F: the Schedule editor's presets, "Runs as", and the
 * Automations edit form keeping a rule's agent. */

describe("the Schedule editor's presets", () => {
  it("reads each preset back from the cron it writes", () => {
    for (const [cron, preset] of [
      ["0 18 * * *", "daily"],
      ["0 18 * * 1-5", "weekdays"],
      ["30 7 * * 1", "weekly"],
    ] as const) {
      const p = presetOf(cron);
      expect(p.preset).toBe(preset);
      expect(presetCron(p)).toBe(cron);
    }
    expect(presetOf("30 7 * * 1")).toMatchObject({ day: 1, time: "07:30" });
  });

  it("keeps anything else as Custom, verbatim, never rewritten", () => {
    for (const cron of ["*/15 * * * *", "0 9 1 * *", "0 9 * * 1,3"]) {
      const p = presetOf(cron);
      expect(p.preset).toBe("custom");
      expect(presetCron(p)).toBe(cron);
    }
  });

  it("writes the chosen weekday and time", () => {
    expect(
      presetCron({ preset: "weekly", time: "16:00", day: 5, cron: "" }),
    ).toBe("0 16 * * 5");
    expect(
      presetCron({ preset: "daily", time: "06:05", day: 1, cron: "" }),
    ).toBe("5 6 * * *");
  });
});

describe("who an automation runs as", () => {
  const agents = [{ name: "wrap-up", display_name: "Evening wrap-up" }];

  it("names the agent, or the lead when it names none", () => {
    expect(runsAs("wrap-up", agents)).toEqual({
      text: "Runs as Evening wrap-up",
      missing: false,
    });
    expect(runsAs(null, agents).text).toBe("Runs as the lead agent");
    expect(runsAs("researcher", undefined).text).toBe("Runs as Researcher");
  });

  it("says a missing agent is missing, never the lead", () => {
    expect(runsAs("gone-agent", agents)).toEqual({
      text: "Runs as Gone agent (agent not found)",
      missing: true,
    });
  });
});

describe("the Automations edit form keeps what it does not show", () => {
  const base = {
    id: "wrap-up-schedule",
    name: "",
    type: "cron",
    enabled: true,
    match: { schedule: "0 18 * * 1-5", timezone: "America/New_York" },
    prompt: "p",
    destination: "quiet",
    urgent: false,
  } as unknown as RuleView;

  it("keeps the agent and show_on_home, so a save never moves the rule to the lead", () => {
    const doc = ruleDocOf({ ...base, agent: "wrap-up", show_on_home: false });
    expect(doc.agent).toBe("wrap-up");
    expect(doc.show_on_home).toBe(false);
  });

  it("adds nothing for a lead rule shown on Home", () => {
    const doc = ruleDocOf({ ...base, agent: null, show_on_home: true });
    expect("agent" in doc).toBe(false);
    expect("show_on_home" in doc).toBe(false);
  });
});
