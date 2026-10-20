import { ArrowRightIcon } from "lucide-react";

import { LEAD_AGENT_ID } from "@/core/agents/avatar";
import { agentLabel, type Handoff } from "@/core/messages/agents";
import { cn } from "@/lib/utils";

import { AgentAvatar } from "../chat-bar/agent-avatar";

/** The lead's avatar reads "L", as on the board; others take their initials. */
function avatarFor(agentId: string, size: number) {
  const lead = agentId === LEAD_AGENT_ID;
  return (
    <AgentAvatar
      id={agentId}
      name={agentLabel(agentId)}
      size={size}
      initials={lead ? "L" : undefined}
    />
  );
}

/**
 * Who is speaking, above an agent's reply in a chat with several agents
 * (Chat.dc.html: a 30 px avatar in the agent's colour, its name, and an
 * optional muted line such as the tools it used).
 */
export function AgentHeader({
  agentId,
  detail,
  className,
}: {
  agentId: string;
  detail?: string;
  className?: string;
}) {
  return (
    <div
      className={cn("flex items-center gap-3", className)}
      data-testid="agent-header"
      data-agent={agentId}
    >
      {avatarFor(agentId, 30)}
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <span className="text-foreground font-semibold">
          {agentLabel(agentId)}
        </span>
        {detail && (
          <span className="text-muted-foreground text-xs">{detail}</span>
        )}
      </div>
    </div>
  );
}

/** "Lead agent → Researcher": one agent handing work to another. */
export function HandoffLine({ handoff }: { handoff: Handoff }) {
  const verb = handoff.via === "task" ? "delegated to" : "handed this to";
  return (
    <div
      className="text-muted-foreground flex items-center gap-2 text-xs"
      data-testid="handoff"
      data-from={handoff.from}
      data-to={handoff.to}
      role="note"
      aria-label={`${agentLabel(handoff.from)} ${verb} ${agentLabel(handoff.to)}`}
    >
      {avatarFor(handoff.from, 18)}
      <span className="text-foreground-2 font-medium">
        {agentLabel(handoff.from)}
      </span>
      <ArrowRightIcon aria-hidden className="size-3.5" />
      {avatarFor(handoff.to, 18)}
      <span className="text-foreground-2 font-medium">
        {agentLabel(handoff.to)}
      </span>
    </div>
  );
}
