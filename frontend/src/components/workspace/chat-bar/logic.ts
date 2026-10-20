/**
 * Pure rules behind the chat bar, kept apart from React so they are tested
 * directly (tests/unit/chat-bar-logic.test.ts).
 */
import type { ToolSource } from "@/core/tool-sources/types";
import type { ToolCatalogItem } from "@/core/tools/api";

export type InputMode = "flash" | "thinking" | "pro" | "ultra";
export type ReasoningEffort = "minimal" | "low" | "medium" | "high";

/** A model that cannot think runs in Flash whatever was picked. */
export function getResolvedMode(
  mode: InputMode | undefined,
  supportsThinking: boolean,
): InputMode {
  if (!supportsThinking && mode !== "flash") {
    return "flash";
  }
  if (mode) {
    return mode;
  }
  return supportsThinking ? "pro" : "flash";
}

/** Picking a mode resets the effort to that mode's default. */
export function effortForMode(mode: InputMode): ReasoningEffort {
  return mode === "ultra"
    ? "high"
    : mode === "pro"
      ? "medium"
      : mode === "thinking"
        ? "low"
        : "minimal";
}

/**
 * The effort control exists only where it does something: the model accepts
 * an effort, and the mode thinks at all.
 */
export function showsReasoningEffort(
  supportsReasoningEffort: boolean,
  mode: InputMode | undefined,
): boolean {
  return supportsReasoningEffort && mode !== "flash";
}

// ---- integrations ------------------------------------------------------------

export type StatusWord =
  | "Live"
  | "Connected"
  | "Off"
  | "Unreachable"
  | "Not connected"
  | "Not checked yet"
  | "Status unknown";

/**
 * design-notes.md §Status vocabulary. One word per gateway state, said in
 * words. "Live" only for what was observed working: a local server that
 * loaded, or a connector whose tool call has come back without error
 * (last_success_at, recorded at the tool-call chokepoint). A Composio
 * connection with no such call is only REPORTED active: "Connected". "Not
 * checked yet" and "Status unknown" are can't-tell, never Live and never Off.
 */
export function statusWord(source: ToolSource | undefined): StatusWord {
  if (!source) return "Status unknown";
  switch (source.state) {
    case "live":
      return "Live";
    case "authorised":
    case "authorised-selected":
    case "authorised-not-selected":
      return source.last_success_at ? "Live" : "Connected";
    case "disabled":
      return "Off";
    case "unreachable":
      return "Unreachable";
    case "not-configured":
    case "not-authorised":
      return "Not connected";
    case "not-loaded":
      return "Not checked yet";
  }
}

export type RowAction =
  | { kind: "switch"; unverified: boolean }
  | { kind: "link"; label: "Check" | "Connect" | "Set up" | "Turn on" };

/**
 * A switch only where turning it on can give the agent tools; everything else
 * links to MCP Suite, where it can be fixed.
 */
export function rowAction(
  word: StatusWord,
  kind: "local" | "connector",
): RowAction {
  switch (word) {
    case "Live":
    case "Connected":
      return { kind: "switch", unverified: false };
    case "Not checked yet":
    case "Status unknown":
      return { kind: "switch", unverified: true };
    case "Off":
      return { kind: "link", label: "Turn on" };
    case "Unreachable":
      return { kind: "link", label: "Check" };
    case "Not connected":
      return {
        kind: "link",
        label: kind === "connector" ? "Connect" : "Set up",
      };
  }
}

export interface IntegrationRow {
  id: string;
  name: string;
  kind: "local" | "connector";
  /** What the logo registry is asked: the toolkit slug or the server name. */
  logoSource: string;
  status: StatusWord;
  /** Tools a live local server contributes; null when not known. */
  toolCount: number | null;
  /** The real load error of an unreachable source. */
  error: string | null;
  /** When a call to it last worked (observed); null when never seen. */
  lastWorkedAt: string | null;
  selected: boolean;
  pinned: boolean;
}

const kindOf = (id: string): "local" | "connector" =>
  id.startsWith("connector:") ? "connector" : "local";

/**
 * The catalog (what can be selected) joined with the live view (what state
 * each source is in) and the thread's selection. A source the live view
 * reports but the catalog lacks (an expected server with no config entry) is
 * listed too, so a missing source is visible rather than absent. Without a
 * Composio key there are no connector rows at all (the picker says why once,
 * instead of eight "Not connected" rows).
 */
export function integrationRows(
  catalog: ToolCatalogItem[],
  sources: ToolSource[] | undefined,
  selected: ReadonlySet<string>,
  pinned: ReadonlySet<string>,
  connectorsAvailable = true,
): IntegrationRow[] {
  const byId = new Map((sources ?? []).map((s) => [s.id, s]));
  const rows: IntegrationRow[] = catalog.map((item) => {
    const isPinned = pinned.has(item.tool_id) || item.pinned;
    const src = byId.get(item.tool_id);
    return {
      id: item.tool_id,
      name: item.name,
      kind: kindOf(item.tool_id),
      logoSource: item.toolkit ?? item.name,
      status: sources ? statusWord(src) : "Status unknown",
      toolCount: src?.tool_count ?? null,
      error: src?.error ?? null,
      lastWorkedAt: src?.last_success_at ?? null,
      selected: isPinned || selected.has(item.tool_id),
      pinned: isPinned,
    };
  });
  const listed = new Set(rows.map((r) => r.id));
  for (const s of sources ?? []) {
    if (listed.has(s.id)) continue;
    rows.push({
      id: s.id,
      name: s.name,
      kind: kindOf(s.id),
      logoSource: s.id,
      status: statusWord(s),
      toolCount: s.tool_count,
      error: s.error,
      lastWorkedAt: s.last_success_at ?? null,
      selected: false,
      pinned: pinned.has(s.id),
    });
  }
  return connectorsAvailable
    ? rows
    : rows.filter((r) => r.kind !== "connector");
}

/** The chips row shows what this chat will actually use. */
export function selectedIntegrations(rows: IntegrationRow[]): IntegrationRow[] {
  return rows.filter((r) => r.selected);
}

/**
 * The skills this chat's agent may use (Open Question 7): an agent's own
 * whitelist when it has one, otherwise every enabled skill. Read-only.
 */
export function agentSkills(
  enabled: string[],
  whitelist: string[] | null | undefined,
): string[] {
  if (!whitelist) return enabled;
  return enabled.filter((s) => whitelist.includes(s));
}

// ---- @ and / triggers --------------------------------------------------------

export interface Trigger {
  kind: "@" | "/";
  /** Text typed after the trigger character. */
  query: string;
  /** Index of the trigger character in the text. */
  start: number;
}

/**
 * Is the caret inside an "@name" or a leading "/command"? "@" counts at the
 * start or after whitespace (an email address is not a mention); "/" only at
 * the very start of the message.
 */
export function findTrigger(text: string, caret: number): Trigger | null {
  const before = text.slice(0, caret);
  const at = /(^|\s)@([\w.-]*)$/.exec(before);
  if (at) {
    return {
      kind: "@",
      query: at[2]!,
      start: before.length - at[2]!.length - 1,
    };
  }
  const slash = /^\/([\w-]*)$/.exec(before);
  if (slash) {
    return { kind: "/", query: slash[1]!, start: 0 };
  }
  return null;
}

/** Agents are mentioned by name; a name with spaces is written with dashes. */
export function mentionToken(name: string): string {
  return `@${name.trim().replace(/\s+/g, "-")}`;
}

/**
 * The status line: "Live · last worked 5 min ago" once a call is known to have
 * worked, "Live · 4 tools" for a loaded server with no call seen, else the word.
 */
export function statusLine(
  row: Pick<IntegrationRow, "status" | "lastWorkedAt" | "toolCount">,
  ago: (iso: string) => string,
): string {
  if (row.status !== "Live") return row.status;
  if (row.lastWorkedAt) return `Live · last worked ${ago(row.lastWorkedAt)}`;
  if (row.toolCount != null) return `Live · ${row.toolCount} tools`;
  return "Live";
}
