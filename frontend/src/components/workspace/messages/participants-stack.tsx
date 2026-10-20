"use client";

import { LEAD_AGENT_ID } from "@/core/agents/avatar";
import { agentLabel } from "@/core/messages/agents";
import { useThreadParticipants } from "@/core/threads/participants";

import { AgentAvatar } from "../chat-bar/agent-avatar";

/**
 * The agents in this chat, next to its title (Chat.dc.html: overlapping
 * avatars and "3 agents"). Read from the thread's membership on the server.
 * Shown once another agent has been called in; a chat with the lead alone
 * keeps its plain header. A membership that cannot be read says so.
 */
export function ParticipantsStack({
  threadId,
  enabled,
  leadAgent = LEAD_AGENT_ID,
}: {
  threadId: string;
  enabled: boolean;
  /** The chat's own agent (a custom agent's chat is led by that agent). */
  leadAgent?: string;
}) {
  const { members, error } = useThreadParticipants(threadId, enabled);
  if (!enabled) return null;
  if (error) {
    return (
      <span
        className="text-muted-foreground text-xs"
        data-testid="participants-unknown"
      >
        Can&apos;t tell which agents are in this chat
      </span>
    );
  }
  const names = [
    leadAgent,
    ...members.map((m) => m.name).filter((n) => n !== leadAgent),
  ];
  if (names.length < 2) return null;
  const labels = names.map(agentLabel);
  return (
    <span className="flex items-center gap-2" data-testid="participants">
      <span
        className="flex items-center"
        role="img"
        aria-label={`Agents in this chat: ${labels.join(", ")}`}
      >
        {names.map((name, index) => (
          <span
            key={name}
            className={
              index === 0
                ? "border-background rounded-full border-2"
                : "border-background -ml-1.5 rounded-full border-2"
            }
          >
            <AgentAvatar
              id={name}
              name={agentLabel(name)}
              size={24}
              initials={name === LEAD_AGENT_ID ? "L" : undefined}
            />
          </span>
        ))}
      </span>
      <span className="text-muted-foreground text-xs">
        {names.length} agents
      </span>
    </span>
  );
}
