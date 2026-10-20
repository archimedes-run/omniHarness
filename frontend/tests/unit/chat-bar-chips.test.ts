import { describe, expect, it } from "vitest";

import {
  backspaceToChips,
  chatSkills,
  chipKey,
  collapse,
  insertMention,
  isUnhealthy,
  withSkill,
} from "@/components/workspace/chat-bar/chips";
import {
  integrationRows,
  modelProvider,
  selectedIntegrations,
} from "@/components/workspace/chat-bar/logic";
import type { ToolSource } from "@/core/tool-sources/types";
import type { ToolCatalogItem } from "@/core/tools/api";

const item = (tool_id: string, name: string): ToolCatalogItem => ({
  tool_id,
  name,
  description: "",
  source: tool_id.startsWith("connector:") ? "connector" : "local",
  origin: "builtin",
  toolkit: null,
  icon: null,
  category: "",
  connected: true,
  pinned: false,
});

const source = (id: string, state: ToolSource["state"]): ToolSource => ({
  id,
  name: id,
  kind: id.startsWith("connector:") ? "connector" : "local",
  state,
  tool_count: null,
  error: null,
  selected: null,
});

const CATALOG = [
  item("connector:GOOGLECALENDAR", "Google Calendar"),
  item("local:github", "github"),
];
const SOURCES = [
  source("connector:GOOGLECALENDAR", "authorised-selected"),
  source("local:github", "live"),
];

describe("removing a chip changes this chat's context", () => {
  it("an integration's × deselects it: the bar drops the chip and the picker's row is off", () => {
    const before = new Set(["connector:GOOGLECALENDAR", "local:github"]);
    const rows = integrationRows(CATALOG, SOURCES, before, new Set());
    expect(selectedIntegrations(rows).map((r) => r.id)).toEqual([
      "connector:GOOGLECALENDAR",
      "local:github",
    ]);
    // The chip's × and the picker's switch write the same selection.
    const after = new Set(before);
    after.delete("connector:GOOGLECALENDAR");
    const next = integrationRows(CATALOG, SOURCES, after, new Set());
    expect(selectedIntegrations(next).map((r) => r.id)).toEqual([
      "local:github",
    ]);
    expect(
      next.find((r) => r.id === "connector:GOOGLECALENDAR")!.selected,
    ).toBe(false);
  });

  it("a skill's × removes it from this chat; the picker's switch brings it back", () => {
    const available = ["changelog", "cite", "chart"];
    const removed = withSkill([], "cite", false);
    expect(removed).toEqual(["cite"]);
    expect(chatSkills(available, removed)).toEqual(["changelog", "chart"]);
    // The picker shows "on" for what is not removed: the same list.
    expect(available.map((s) => !removed.includes(s))).toEqual([
      true,
      false,
      true,
    ]);
    const back = withSkill(removed, "cite", true);
    expect(back).toEqual([]);
    expect(chatSkills(available, back)).toEqual(available);
  });

  it("removing twice, or turning on what is on, changes nothing", () => {
    expect(withSkill(["cite"], "cite", false)).toEqual(["cite"]);
    expect(withSkill([], "cite", true)).toEqual([]);
  });
});

describe("overflow", () => {
  it("shows the first N and counts the rest; expanded shows all", () => {
    const skills = ["a", "b", "c", "d", "e"];
    expect(collapse(skills, 2, false)).toEqual({
      visible: ["a", "b"],
      hidden: 3,
    });
    expect(collapse(skills, 2, true)).toEqual({ visible: skills, hidden: 0 });
    expect(collapse(["a"], 2, false)).toEqual({ visible: ["a"], hidden: 0 });
  });

  it("never hides an unhealthy integration, which counts toward the limit", () => {
    const rows = ["ok1", "ok2", "dead", "ok3", "ok4", "ok5"].map((id) => ({
      id,
      status: id === "dead" ? ("Unreachable" as const) : ("Live" as const),
    }));
    const { visible, hidden } = collapse(rows, 4, false, (r) =>
      isUnhealthy(r.status),
    );
    expect(visible.map((r) => r.id)).toEqual(["ok1", "ok2", "dead", "ok3"]);
    expect(hidden).toBe(2);
    const late = collapse([...rows.slice(3), rows[2]!], 1, false, (r) =>
      isUnhealthy(r.status),
    );
    expect(late.visible.map((r) => r.id)).toEqual(["dead"]);
  });

  it("only not-working states are unhealthy; can't-tell is not", () => {
    expect(isUnhealthy("Unreachable")).toBe(true);
    expect(isUnhealthy("Off")).toBe(true);
    expect(isUnhealthy("Not connected")).toBe(true);
    expect(isUnhealthy("Live")).toBe(false);
    expect(isUnhealthy("Not checked yet")).toBe(false);
    expect(isUnhealthy("Status unknown")).toBe(false);
  });
});

describe("keyboard", () => {
  const chips = [
    { removable: true },
    { removable: false },
    { removable: true },
  ];

  it("Backspace in an empty message goes to the chips; with text it does not", () => {
    expect(backspaceToChips("", 3)).toBe(true);
    expect(backspaceToChips("x", 3)).toBe(false);
    expect(backspaceToChips("", 0)).toBe(false);
  });

  it("Backspace or Delete removes a removable chip and picks the neighbour", () => {
    expect(chipKey("Backspace", 2, chips)).toEqual({
      kind: "remove",
      index: 2,
      focusAfter: 1,
    });
    expect(chipKey("Delete", 0, chips)).toEqual({
      kind: "remove",
      index: 0,
      focusAfter: 0,
    });
    expect(chipKey("Delete", 2, chips)).toEqual({
      kind: "remove",
      index: 2,
      focusAfter: 1,
    });
    expect(chipKey("Backspace", 0, [{ removable: true }])).toEqual({
      kind: "remove",
      index: 0,
      focusAfter: "textarea",
    });
  });

  it("a chip that cannot be removed stays", () => {
    expect(chipKey("Backspace", 1, chips)).toBeNull();
    expect(chipKey("Delete", 1, chips)).toBeNull();
  });

  it("arrows move between chips; past the last is the message; Esc too", () => {
    expect(chipKey("ArrowLeft", 1, chips)).toEqual({ kind: "focus", index: 0 });
    expect(chipKey("ArrowLeft", 0, chips)).toBeNull();
    expect(chipKey("ArrowRight", 0, chips)).toEqual({
      kind: "focus",
      index: 1,
    });
    expect(chipKey("ArrowRight", 2, chips)).toEqual({ kind: "textarea" });
    expect(chipKey("Home", 2, chips)).toEqual({ kind: "focus", index: 0 });
    expect(chipKey("End", 0, chips)).toEqual({ kind: "focus", index: 2 });
    expect(chipKey("Escape", 1, chips)).toEqual({ kind: "textarea" });
    expect(chipKey("a", 1, chips)).toBeNull();
  });
});

describe("the @ mention", () => {
  it("keeps the text on both sides and puts the caret after the mention", () => {
    const text = "check @res";
    expect(
      insertMention(text, { start: 6 }, text.length, "researcher"),
    ).toEqual({ text: "check @researcher ", caret: 18 });
    const mid = "check @res the calendar";
    expect(insertMention(mid, { start: 6 }, 10, "researcher")).toEqual({
      text: "check @researcher the calendar",
      caret: 18,
    });
  });

  it("writes a name with spaces with dashes", () => {
    expect(insertMention("@", { start: 0 }, 1, "Release Manager").text).toBe(
      "@Release-Manager ",
    );
  });
});

describe("the model's provider logo", () => {
  it("is told from the model id, or not at all", () => {
    expect(modelProvider("gpt-5")).toBe("openai");
    expect(modelProvider("openai/gpt-5-mini")).toBe("openai");
    expect(modelProvider("o3")).toBe("openai");
    expect(modelProvider("claude-sonnet-5-5")).toBe("anthropic");
    expect(modelProvider("deepseek-chat")).toBeNull();
    expect(modelProvider(undefined)).toBeNull();
  });
});
