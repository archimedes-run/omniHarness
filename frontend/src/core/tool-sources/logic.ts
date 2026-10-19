import type { ToolSource } from "./types";

export type Tone = "ok" | "off" | "problem" | "unknown";

export interface StateDescription {
  label: string;
  /** What the state means for the agent, in a sentence. */
  meaning: string;
  tone: Tone;
}

/**
 * Settings → Connections shows four statuses (Phase 2.5): Not configured, Off,
 * Unreachable, Live. "Not loaded yet" stays apart because it means "cannot
 * tell yet", not off; and inside a conversation a connector also says whether
 * that conversation selected it.
 *
 * One description per state, and every state distinct (FR-040). The four
 * that used to look identical — never configured, switched off, failing,
 * working — each say what they are and what it means for the agent, because
 * "the agent does not have this tool" has four different fixes.
 */
export function describeState(source: ToolSource): StateDescription {
  switch (source.state) {
    case "live":
      return {
        label: "Live",
        meaning: `Loaded, contributing ${source.tool_count ?? 0} tool(s).`,
        tone: "ok",
      };
    case "unreachable":
      return {
        label: "Unreachable",
        meaning:
          "Configured and enabled, but loading it failed — agents do not have its tools.",
        tone: "problem",
      };
    case "disabled":
      return {
        label: "Off",
        meaning: "Configured, and switched off.",
        tone: "off",
      };
    case "not-configured":
      return {
        label: "Not configured",
        meaning: "Expected, but there is no entry for it.",
        tone: "off",
      };
    case "not-loaded":
      return {
        label: "Not loaded yet",
        meaning: "Configured; nothing has tried to load it in this worker.",
        tone: "unknown",
      };
    case "authorised-selected":
      return {
        label: "Authorised · in this chat",
        meaning: "Connected, and selected in this conversation.",
        tone: "ok",
      };
    case "authorised-not-selected":
      return {
        label: "Authorised · not in this chat",
        meaning:
          "Connected, but this conversation has not selected it — no need to authorise again.",
        tone: "off",
      };
    case "authorised":
      return {
        label: "Live",
        meaning: "Connected. A conversation must select it to use it.",
        tone: "ok",
      };
    case "not-authorised":
      return {
        label: "Not configured",
        meaning: "No connection yet. Connect it to use it.",
        tone: "off",
      };
  }
}
