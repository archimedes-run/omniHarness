import { describe, expect, it } from "vitest";

import {
  agentFields,
  anyDirty,
  scheduleChanges,
  stepDirty,
  type AgentForm,
  type SchedRow,
} from "@/components/workspace/studio/agent-form";
import {
  AVATARS,
  LEAD_AGENT_ID,
  avatarIdFor,
  avatarSrc,
  isAvatarId,
  randomAvatar,
} from "@/core/agents";
import { agentStatus, nextRunLine } from "@/core/studio/agent-status";
import {
  cronOf,
  editOf,
  nextRuns,
  recurrenceText,
  zonedInstant,
} from "@/core/studio/schedule-lang";
import {
  allowlistOf,
  asksFirst,
  draftedSelection,
  legacySelection,
  selectionOf,
} from "@/core/studio/tool-select";
import type { AgentRuns, ToolCatalog } from "@/core/studio/types";

const T = (name: string, tier: 1 | 2 | 3 | null) => ({
  name,
  short: name,
  label: name,
  description: "",
  tier,
  common: true,
});

const CATALOG: ToolCatalog = {
  rules_error: null,
  connectors_available: true,
  integrations: [
    {
      id: "connector:GMAIL",
      name: "Gmail",
      kind: "app",
      status: "connected",
      detail: "",
      tools: [
        T("g_read", 1),
        T("g_draft", 2),
        T("g_trash", 3),
        T("g_send", null),
      ],
    },
    {
      id: "connector:SLACK",
      name: "Slack",
      kind: "app",
      status: "not_connected",
      detail: "",
      tools: [],
    },
    {
      id: "local:filesystem",
      name: "filesystem",
      kind: "mcp",
      status: "connected",
      detail: "",
      tools: [T("fs_read", 1)],
    },
    {
      id: "local:notes",
      name: "notes",
      kind: "custom",
      status: "unreachable",
      detail: "",
      tools: [],
    },
    {
      id: "builtin:web",
      name: "Web",
      kind: "builtin",
      status: "connected",
      detail: "",
      tools: [T("web_search", 1), T("web_fetch", 1)],
    },
    {
      id: "builtin:bash",
      name: "Shell",
      kind: "builtin",
      status: "connected",
      detail: "",
      tools: [T("bash", 3)],
    },
    {
      id: "builtin:ledger",
      name: "Tasks",
      kind: "builtin",
      status: "connected",
      detail: "",
      tools: [T("ledger_read", 1)],
    },
  ],
};

describe("avatars", () => {
  it("the lead is always Merlo, a saved face is kept, an unknown one falls back to a stable default", () => {
    expect(AVATARS).toHaveLength(20);
    expect(avatarIdFor(LEAD_AGENT_ID, "pip")).toBe("merlo");
    expect(avatarIdFor("wrap-up", "snooze")).toBe("snooze");
    const fallback = avatarIdFor("wrap-up", "../../etc/passwd");
    expect(isAvatarId(fallback)).toBe(true);
    expect(avatarIdFor("wrap-up", null)).toBe(fallback);
    expect(avatarIdFor("Wrap-Up", undefined)).toBe(fallback);
  });

  it("only a known id ever reaches an image URL", () => {
    expect(avatarSrc("pip")).toBe("/avatars/pip.svg");
    expect(avatarSrc("../secret")).toBe("/avatars/merlo.svg");
  });

  it("Surprise me never picks the current face", () => {
    for (let i = 0; i < 40; i++)
      expect(randomAvatar("pip", () => i / 40)).not.toBe("pip");
  });
});

describe("schedules in words", () => {
  it("reads and writes the presets the editor offers, and keeps a cron it cannot show", () => {
    expect(editOf("30 18 * * 1-5", "UTC")).toMatchObject({
      preset: "weekdays",
      time: "18:30",
    });
    expect(editOf("0 9 * * *", "UTC")).toMatchObject({
      preset: "daily",
      time: "09:00",
    });
    expect(editOf("30 8 * * 1,3", "UTC")).toMatchObject({
      preset: "weekly",
      days: [1, 3],
    });
    expect(editOf("*/15 * * * *", "UTC")).toMatchObject({
      preset: "custom",
      cron: "*/15 * * * *",
    });
    expect(
      cronOf({
        preset: "weekly",
        time: "08:30",
        days: [3, 1],
        cron: "",
        timezone: "UTC",
      }),
    ).toBe("30 8 * * 1,3");
    expect(
      cronOf({
        preset: "weekdays",
        time: "18:00",
        days: [],
        cron: "",
        timezone: "UTC",
      }),
    ).toBe("0 18 * * 1-5");
    expect(
      cronOf({
        preset: "weekly",
        time: "08:30",
        days: [],
        cron: "",
        timezone: "UTC",
      }),
    ).toBe("");
  });

  it("says when it runs, in the schedule's zone", () => {
    expect(recurrenceText("30 18 * * 1-5", "UTC")).toBe(
      "Every weekday at 6:30 PM UTC",
    );
    expect(recurrenceText("30 16 * * 5", "UTC")).toBe(
      "Every Friday at 4:30 PM UTC",
    );
    expect(recurrenceText("0 8 * * 1,3", "UTC")).toBe(
      "Every Mon and Wed at 8:00 AM UTC",
    );
    expect(recurrenceText("0 8 * * 0,6", "UTC")).toBe(
      "Every weekend at 8:00 AM UTC",
    );
    expect(recurrenceText("*/5 * * * *", "UTC")).toBe(
      "Custom schedule (*/5 * * * *, UTC)",
    );
  });

  it("computes the next runs as the engine would: the wall clock in the schedule's zone", () => {
    // Fri 23 Oct 2026, 14:10 in New York.
    const now = zonedInstant(2026, 9, 23, 14, 10, "America/New_York");
    const runs = nextRuns("30 8 * * 1,3", "America/Chicago", now, 3);
    expect(runs.map((d) => d.toISOString())).toEqual([
      "2026-10-26T13:30:00.000Z", // Mon 8:30 CDT
      "2026-10-28T13:30:00.000Z", // Wed 8:30 CDT
      "2026-11-02T14:30:00.000Z", // Mon 8:30 CST (after the clocks change)
    ]);
    expect(nextRuns("*/15 * * * *", "UTC", now)).toEqual([]);
  });
});

const runs = (
  schedules: { enabled: boolean; next_run?: string | null }[],
  recent = 0,
): AgentRuns => ({
  agent: "a",
  engine_enabled: true,
  not_set_up_reason: null,
  rules_error: null,
  rules_version: "v1",
  writable: true,
  recent: Array.from(
    { length: recent },
    () => ({}) as AgentRuns["recent"][number],
  ),
  schedules: schedules.map((s, i) => ({
    rule_id: `r${i}`,
    schedule: "0 9 * * *",
    timezone: "UTC",
    timezone_named: true,
    enabled: s.enabled,
    next_run: s.next_run ?? null,
    held_until: null,
    error: null,
    name: "",
    prompt: "",
    telegram: true,
    show_on_home: true,
  })),
});

describe("agent status (owner decision 1)", () => {
  it("is Draft without instructions, On demand without a schedule, Paused when every schedule is off", () => {
    expect(agentStatus("", runs([{ enabled: true }]))).toBe("draft");
    expect(agentStatus("Do it", runs([]))).toBe("ondemand");
    expect(
      agentStatus("Do it", runs([{ enabled: false }, { enabled: false }])),
    ).toBe("paused");
    expect(agentStatus("Do it", undefined)).toBeNull();
  });

  it("is Scheduled before its first run and Active after", () => {
    expect(agentStatus("Do it", runs([{ enabled: true }]))).toBe("scheduled");
    expect(
      agentStatus("Do it", runs([{ enabled: true }, { enabled: false }], 1)),
    ).toBe("active");
  });

  it("names the soonest run of the switched-on schedules", () => {
    const now = new Date("2026-10-23T18:10:00Z");
    const r = runs([
      { enabled: true, next_run: "2026-10-30T13:00:00Z" },
      { enabled: false, next_run: "2026-10-24T13:00:00Z" },
    ]);
    expect(nextRunLine("scheduled", r, now)).toMatch(/^First run Oct 30, /);
    expect(nextRunLine("ondemand", r, now)).toBe("When you ask");
    expect(nextRunLine("paused", r, now)).toBe("Paused");
  });
});

describe("tool ticks", () => {
  it("an allowlist ticks only tools of integrations it names", () => {
    expect(
      selectionOf(
        { integrations: ["connector:GMAIL"], tools: ["g_read", "web_search"] },
        CATALOG,
      ),
    ).toEqual({ "connector:GMAIL": ["g_read"] });
  });

  it("an agent saved before 006-G shows its groups' tools, the ledger and the pinned servers; never an app", () => {
    expect(legacySelection(["web"], CATALOG)).toEqual({
      "local:filesystem": ["fs_read"],
      "builtin:web": ["web_search", "web_fetch"],
      "builtin:ledger": ["ledger_read"],
    });
    expect(Object.keys(legacySelection(null, CATALOG))).toContain(
      "builtin:bash",
    );
  });

  it("saving keeps a choice the catalog cannot show right now", () => {
    const previous = {
      integrations: ["connector:GMAIL", "local:notes"],
      tools: ["g_read", "notes_read"],
    };
    expect(
      allowlistOf(
        { "connector:GMAIL": ["g_read", "g_draft"] },
        CATALOG,
        previous,
      ),
    ).toEqual({
      integrations: ["connector:GMAIL", "local:notes"],
      tools: ["g_draft", "g_read", "notes_read"],
    });
    // Unticking everything in a shown integration drops it.
    expect(
      allowlistOf({ "connector:GMAIL": [] }, CATALOG, {
        integrations: ["connector:GMAIL"],
        tools: ["g_read"],
      }),
    ).toEqual({ integrations: [], tools: [] });
  });

  it("a drafted integration ticks what does not ask first; asks-first and unruled tools stay off", () => {
    expect(
      draftedSelection(["connector:GMAIL", "connector:SLACK", "nope"], CATALOG),
    ).toEqual({ "connector:GMAIL": ["g_read", "g_draft"] });
  });

  it("lists the ticked tools that always ask first", () => {
    expect(
      asksFirst(
        { "connector:GMAIL": ["g_trash", "g_read"], "builtin:bash": ["bash"] },
        CATALOG,
      ).map((x) => x.name),
    ).toEqual(["g_trash", "bash"]);
  });
});

const row = (over: Partial<SchedRow> = {}): SchedRow => ({
  key: "r1",
  ruleId: "r1",
  cron: "0 9 * * *",
  timezone: "UTC",
  prompt: "Run",
  name: "",
  telegram: true,
  home: true,
  enabled: true,
  nextRun: null,
  heldUntil: null,
  ...over,
});

const form = (over: Partial<AgentForm> = {}): AgentForm => ({
  avatar: "pip",
  name: "Wrap-up",
  sentence: "Wraps up",
  instructions: "Do it",
  selection: { "builtin:web": ["web_search"] },
  toolsTouched: false,
  skills: null,
  grants: [],
  schedules: [row()],
  notify: { telegram: true, home: true },
  ...over,
});

describe("what a save writes", () => {
  it("schedules: creates the new, updates the changed, deletes the removed, leaves the rest", () => {
    const orig = [
      row(),
      row({ key: "r2", ruleId: "r2" }),
      row({ key: "r3", ruleId: "r3" }),
    ];
    const next = [
      row(),
      row({ key: "r2", ruleId: "r2", enabled: false }),
      row({ key: "n", ruleId: null, cron: "0 8 * * 1" }),
    ];
    expect(
      scheduleChanges(next, orig).map((c) => [
        c.kind,
        "ruleId" in c ? c.ruleId : null,
      ]),
    ).toEqual([
      ["update", "r2"],
      ["create", null],
      ["delete", "r3"],
    ]);
  });

  it("only the agent fields that changed, and tools only when a tick changed", () => {
    const orig = form();
    expect(agentFields(form({ name: "Digest" }), orig, null)).toEqual({
      display_name: "Digest",
    });
    // A selection that differs but was never touched (a legacy agent's
    // derived ticks) is not unsaved and is not written.
    const untouched = form({
      selection: { "builtin:web": ["web_search", "web_fetch"] },
    });
    expect(stepDirty(untouched, orig, 2)).toBe(false);
    expect(anyDirty(untouched, orig)).toBe(false);
    const touched = { ...untouched, toolsTouched: true };
    expect(stepDirty(touched, orig, 2)).toBe(true);
    expect(
      agentFields(touched, orig, {
        integrations: ["builtin:web"],
        tools: ["web_fetch", "web_search"],
      }),
    ).toEqual({
      tools: {
        integrations: ["builtin:web"],
        tools: ["web_fetch", "web_search"],
      },
    });
  });
});
