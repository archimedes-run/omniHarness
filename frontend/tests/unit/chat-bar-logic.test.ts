import { describe, expect, it } from "vitest";

import {
  BUILTIN_COMMANDS,
  matchCommands,
} from "@/components/workspace/chat-bar/commands";
import {
  agentSkills,
  connectWords,
  effortForMode,
  findTrigger,
  getResolvedMode,
  integrationRows,
  rowAction,
  selectedIntegrations,
  showsReasoningEffort,
  statusLine,
  statusWord,
} from "@/components/workspace/chat-bar/logic";
import type { ToolSource } from "@/core/tool-sources/types";
import type { ToolCatalogItem } from "@/core/tools/api";

const src = (
  id: string,
  state: ToolSource["state"],
  extra: Partial<ToolSource> = {},
): ToolSource => ({
  id,
  name: id.split(":")[1]!,
  kind: id.startsWith("connector:") ? "connector" : "local",
  state,
  tool_count: null,
  error: null,
  selected: null,
  ...extra,
});

const item = (
  tool_id: string,
  extra: Partial<ToolCatalogItem> = {},
): ToolCatalogItem => ({
  tool_id,
  name: tool_id.split(":")[1]!,
  description: "",
  source: tool_id.startsWith("connector:") ? "connector" : "local",
  origin: "builtin",
  toolkit: tool_id.startsWith("connector:") ? tool_id.split(":")[1]! : null,
  icon: null,
  category: "Productivity",
  connected: true,
  pinned: false,
  ...extra,
});

describe("status words (design-notes.md §Status vocabulary)", () => {
  it.each([
    ["live", "Live"],
    ["disabled", "Off"],
    ["unreachable", "Unreachable"],
    ["not-configured", "Not connected"],
    ["not-loaded", "Not checked yet"],
    ["authorised", "Connected"],
    ["authorised-selected", "Connected"],
    ["authorised-not-selected", "Connected"],
    ["not-authorised", "Not connected"],
  ] as const)("%s reads %s", (state, word) => {
    expect(statusWord(src("local:x", state))).toBe(word);
  });

  it("a connector only REPORTED active is never Live", () => {
    expect(statusWord(src("connector:GMAIL", "authorised"))).not.toBe("Live");
  });

  it("a source never checked, or one the view does not report, is can't-tell", () => {
    expect(statusWord(src("local:x", "not-loaded"))).toBe("Not checked yet");
    expect(statusWord(undefined)).toBe("Status unknown");
  });

  it("only usable sources get a switch; the rest link to MCP Suite", () => {
    expect(rowAction("Live", "local")).toEqual({
      kind: "switch",
      unverified: false,
    });
    expect(rowAction("Connected", "connector")).toEqual({
      kind: "switch",
      unverified: false,
    });
    expect(rowAction("Not checked yet", "local")).toEqual({
      kind: "switch",
      unverified: true,
    });
    expect(rowAction("Unreachable", "local")).toEqual({
      kind: "link",
      label: "Check",
    });
    expect(rowAction("Off", "local")).toEqual({
      kind: "link",
      label: "Turn on",
    });
    expect(rowAction("Not connected", "connector")).toEqual({
      kind: "link",
      label: "Connect",
    });
    expect(rowAction("Not connected", "local")).toEqual({
      kind: "link",
      label: "Set up",
    });
  });
});

describe("integration rows: the thread's tool selection, made visible", () => {
  const catalog = [
    item("local:filesystem", { pinned: true }),
    item("local:dead"),
    item("connector:GMAIL"),
    item("connector:SLACK", { connected: false }),
  ];
  const sources = [
    src("local:filesystem", "live", { tool_count: 4 }),
    src("local:dead", "unreachable", { error: "ConnectError: refused" }),
    src("connector:GMAIL", "authorised-selected"),
    src("connector:SLACK", "not-authorised"),
    src("local:session-watcher", "not-configured"),
  ];

  it("joins the catalog, the live state and the selection", () => {
    const rows = integrationRows(
      catalog,
      sources,
      new Set(["connector:GMAIL"]),
      new Set(["local:filesystem"]),
    );
    const by = Object.fromEntries(rows.map((r) => [r.id, r]));
    expect(by["local:filesystem"]).toMatchObject({
      status: "Live",
      toolCount: 4,
      pinned: true,
      selected: true,
    });
    expect(by["local:dead"]).toMatchObject({
      status: "Unreachable",
      error: "ConnectError: refused",
      selected: false,
    });
    expect(by["connector:GMAIL"]).toMatchObject({
      status: "Connected",
      selected: true,
      logoSource: "GMAIL",
    });
    expect(by["connector:SLACK"]!.status).toBe("Not connected");
  });

  it("lists an expected source the catalog lacks, so missing is visible", () => {
    const rows = integrationRows(catalog, sources, new Set(), new Set());
    expect(rows.find((r) => r.id === "local:session-watcher")?.status).toBe(
      "Not connected",
    );
  });

  it("an unreadable live view makes every status unknown, not Off", () => {
    const rows = integrationRows(catalog, undefined, new Set(), new Set());
    expect(new Set(rows.map((r) => r.status))).toEqual(
      new Set(["Status unknown"]),
    );
  });

  it("without a Composio key there are no connector rows", () => {
    const rows = integrationRows(catalog, sources, new Set(), new Set(), false);
    expect(rows.some((r) => r.kind === "connector")).toBe(false);
  });

  it("the chip shows exactly what is selected (pinned included)", () => {
    const rows = integrationRows(
      catalog,
      sources,
      new Set(["connector:GMAIL"]),
      new Set(["local:filesystem"]),
    );
    expect(selectedIntegrations(rows).map((r) => r.id)).toEqual([
      "local:filesystem",
      "connector:GMAIL",
    ]);
  });
});

describe("model, mode and effort", () => {
  it("collapses every mode to Flash when the model cannot think", () => {
    for (const m of ["thinking", "pro", "ultra"] as const) {
      expect(getResolvedMode(m, false)).toBe("flash");
    }
    expect(getResolvedMode(undefined, true)).toBe("pro");
  });

  it("picking a mode resets the effort to its default", () => {
    expect(
      ["flash", "thinking", "pro", "ultra"].map((m) =>
        effortForMode(m as "flash"),
      ),
    ).toEqual(["minimal", "low", "medium", "high"]);
  });

  it("the effort control shows only when the model supports it and the mode thinks", () => {
    expect(showsReasoningEffort(true, "pro")).toBe(true);
    expect(showsReasoningEffort(false, "pro")).toBe(false);
    expect(showsReasoningEffort(true, "flash")).toBe(false);
  });
});

describe("@ and / triggers", () => {
  it("@ opens at the start or after a space, never inside an email address", () => {
    expect(findTrigger("@Re", 3)).toEqual({ kind: "@", query: "Re", start: 0 });
    expect(findTrigger("ask @res", 8)).toEqual({
      kind: "@",
      query: "res",
      start: 4,
    });
    expect(findTrigger("me@example", 10)).toBeNull();
  });

  it("/ opens only at the very start of the message", () => {
    expect(findTrigger("/pro", 4)).toEqual({
      kind: "/",
      query: "pro",
      start: 0,
    });
    expect(findTrigger("see /pro", 8)).toBeNull();
    expect(findTrigger("/new thing", 10)).toBeNull();
  });

  it("every listed command does something real", () => {
    expect(BUILTIN_COMMANDS.map((c) => c.name)).toEqual([
      "new",
      "project",
      "agent",
      "integrations",
      "skill",
      "attach",
    ]);
    expect(matchCommands("pr").map((c) => c.name)).toEqual(["project"]);
  });
});

describe("skills chip (read-only, Open Question 7)", () => {
  it("an agent's whitelist narrows the enabled skills; none means all", () => {
    expect(agentSkills(["a", "b", "c"], ["b", "z"])).toEqual(["b"]);
    expect(agentSkills(["a", "b"], null)).toEqual(["a", "b"]);
    expect(agentSkills(["a", "b"], [])).toEqual([]);
  });
});

describe("two-stage status: Connected, then Live · last worked", () => {
  it("a connector reads Connected until a call from it has worked", () => {
    expect(statusWord(src("connector:GMAIL", "authorised"))).toBe("Connected");
    expect(
      statusWord(
        src("connector:GMAIL", "authorised", {
          last_success_at: "2026-10-19T09:00:00Z",
        }),
      ),
    ).toBe("Live");
  });

  it("a failure alone never makes it Live", () => {
    expect(
      statusWord(
        src("connector:GMAIL", "authorised-selected", {
          last_failure_at: "2026-10-19T09:00:00Z",
          last_error: "401",
        }),
      ),
    ).toBe("Connected");
  });

  it("the line says when it last worked, or what was observed instead", () => {
    const ago = () => "5 minutes ago";
    expect(
      statusLine(
        { status: "Live", lastWorkedAt: "2026-10-19T09:00:00Z", toolCount: 4 },
        ago,
      ),
    ).toBe("Live · last worked 5 minutes ago");
    expect(
      statusLine({ status: "Live", lastWorkedAt: null, toolCount: 4 }, ago),
    ).toBe("Live · 4 tools");
    expect(
      statusLine(
        { status: "Connected", lastWorkedAt: null, toolCount: null },
        ago,
      ),
    ).toBe("Connected");
  });

  it("rows carry the observed time from the view", () => {
    const rows = integrationRows(
      [item("connector:GMAIL")],
      [
        src("connector:GMAIL", "authorised", {
          last_success_at: "2026-10-19T09:00:00Z",
        }),
      ],
      new Set(),
      new Set(),
    );
    expect(rows[0]).toMatchObject({
      status: "Live",
      lastWorkedAt: "2026-10-19T09:00:00Z",
    });
  });
});

describe("connectWords: an inline Connect says how it ended, in words", () => {
  it("says blocked, cancelled, failed and timed-out apart", () => {
    expect(connectWords("blocked")?.text).toMatch(/blocked the sign-in pop-up/);
    expect(connectWords("cancelled")?.text).toBe(
      "Sign-in cancelled. Nothing was connected.",
    );
    expect(connectWords("failed")?.text).toBe(
      "Sign-in failed. Nothing was connected.",
    );
    expect(connectWords("failed", "Unknown toolkit")?.text).toBe(
      "Sign-in failed: Unknown toolkit",
    );
    expect(connectWords("timed-out")?.text).toMatch(/did not finish/);
  });
  it("leaves Connected to the row's own status word", () => {
    expect(connectWords("connected")).toBeNull();
  });
});
