/**
 * Who said what in a chat with several agents (Feature 006, Phase 2).
 *
 * The backend attributes an agent's reply with the message's `name` (an agent
 * called in with "@", or a confirmed call's result posted as the agent that
 * proposed it). An assistant message with no name is the lead agent's.
 * A hand-off is the lead's tool call that gives work to another agent:
 * `call_agent` (called in by the user) or `task` (a delegation).
 */
import type { Message } from "@langchain/langgraph-sdk";

import { LEAD_AGENT_ID } from "@/core/agents/avatar";

/** The agent an assistant message speaks for. */
export function agentOf(message: Message): string {
  if (message.type !== "ai") return LEAD_AGENT_ID;
  const name = typeof message.name === "string" ? message.name.trim() : "";
  return name || LEAD_AGENT_ID;
}

/** "release-manager" -> "Release manager"; the lead is "Lead agent". */
export function agentLabel(agentId: string): string {
  const id = agentId.trim();
  if (!id || id === LEAD_AGENT_ID || id === "lead") return "Lead agent";
  const words = id.replace(/[_-]+/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export type Handoff = { from: string; to: string; via: "call_agent" | "task" };

/** The hand-offs an assistant message makes, in call order. */
export function handoffsOf(message: Message): Handoff[] {
  if (message.type !== "ai") return [];
  const out: Handoff[] = [];
  for (const call of message.tool_calls ?? []) {
    const args = (call.args ?? {}) as Record<string, unknown>;
    if (call.name === "call_agent" && typeof args.agent === "string") {
      out.push({ from: agentOf(message), to: args.agent, via: "call_agent" });
    } else if (call.name === "task" && typeof args.subagent_type === "string") {
      out.push({ from: agentOf(message), to: args.subagent_type, via: "task" });
    }
  }
  return out;
}

/**
 * True when more than one agent takes part: another agent replied, or work
 * was handed to one. Only then does each reply carry its agent's header: a
 * chat with the lead alone reads as it always has.
 */
export function isMultiAgent(messages: Message[]): boolean {
  return messages.some(
    (message) =>
      (message.type === "ai" && agentOf(message) !== LEAD_AGENT_ID) ||
      handoffsOf(message).length > 0,
  );
}

function textOf(message: Message): string {
  const content = message.content as unknown;
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content
      .map((part) =>
        typeof part === "string"
          ? part
          : typeof (part as { text?: unknown }).text === "string"
            ? (part as { text: string }).text
            : "",
      )
      .join(" ");
  }
  return "";
}

/**
 * Where each pending action was raised: the index of the first message that
 * names it. A plan names its action ("Action `id`."), and a stopped agent's
 * result names what it is waiting on. Unnamed actions are absent: the caller
 * shows those after the last message.
 */
export function anchorActions(
  messages: Message[],
  actionIds: string[],
): Map<string, number> {
  const anchors = new Map<string, number>();
  if (actionIds.length === 0) return anchors;
  messages.forEach((message, index) => {
    const text = textOf(message);
    if (!text) return;
    for (const id of actionIds) {
      if (!anchors.has(id) && text.includes(id)) anchors.set(id, index);
    }
  });
  return anchors;
}

// ---------------------------------------------------------------------------
// Holding back a verdict-looking line while a reply streams
// ---------------------------------------------------------------------------

/** The backend's closed sets (app/policy/confirm.py _CONFIRM_FORMS, _DECLINE_FORMS). */
const VERDICT_FORMS = [
  "yes",
  "y",
  "confirm",
  "confirmed",
  "approve",
  "approved",
  "go ahead",
  "do it",
  "proceed",
  "yes please",
  "yes do it",
  "sure",
  "ok",
  "no",
  "n",
  "decline",
  "declined",
  "cancel",
  "cancelled",
  "stop",
  "don't",
  "do not",
  "nope",
  "no thanks",
  "never mind",
  "not now",
];

const HEX_RUN = /\b[0-9a-f]{4,12}\b/g;

function normalise(line: string): string {
  return line
    .toLowerCase()
    .replace(/[^a-z0-9' ]+/g, " ")
    .split(/\s+/)
    .filter(Boolean)
    .join(" ");
}

/**
 * A line that is, or is still becoming, a verdict on an action ("yes
 * 7bf9d7ecb3b1"). The backend replaces such a line in the FINISHED reply
 * (PolicyMiddleware._guard_self_verdict), so the assistant never appears to
 * confirm for the user; while the reply streams, the raw tokens arrive first.
 */
export function looksLikeVerdict(line: string, inProgress: boolean): boolean {
  const normal = normalise(line);
  if (!normal) return false;
  const hasId = (normal.match(HEX_RUN) ?? []).length > 0;
  const words = normal
    .replace(HEX_RUN, " ")
    .split(/\s+/)
    .filter(Boolean)
    .join(" ");
  if (hasId && VERDICT_FORMS.includes(words)) return true;
  // The last line is still arriving: hold it while it could become one.
  if (inProgress) {
    return VERDICT_FORMS.some(
      (form) => form === words || (words.length > 0 && form.startsWith(words)),
    );
  }
  return false;
}

/**
 * The text to show while a reply streams: verdict-looking lines held back
 * until the reply completes (then the backend's corrected text is shown).
 */
export function holdBackVerdictLines(text: string, streaming: boolean): string {
  if (!streaming || !text) return text;
  const lines = text.split("\n");
  const last = lines.length - 1;
  return lines
    .filter((line, index) => !looksLikeVerdict(line, index === last))
    .join("\n");
}
