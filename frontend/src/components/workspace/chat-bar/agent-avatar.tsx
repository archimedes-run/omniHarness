"use client";

import { avatarIdFor, avatarMeta, avatarSrc, useAgents } from "@/core/agents";
import { cn } from "@/lib/utils";

/**
 * An agent's face (006-G): the avatar saved with it, Merlo for the lead, or a
 * stable default for an agent saved before avatars existed. Everywhere an
 * agent shows (chat, Home, Automations "Runs as", @-mentions, the Studio) it
 * is this one component, so the face is the same everywhere.
 *
 * Decorative: the agent's name is always written beside it.
 */
export function AgentAvatar({
  id,
  size = 26,
  avatar,
  className,
}: {
  id: string;
  /** Kept for callers; the name is shown next to the avatar, not in it. */
  name?: string;
  size?: number;
  /** Kept for callers; the lead's face is fixed (Merlo). */
  initials?: string;
  /** The saved avatar when the caller has it; else read from the agents list. */
  avatar?: string | null;
  className?: string;
}) {
  const { agents } = useAgents();
  const saved =
    avatar !== undefined
      ? avatar
      : (agents.find((a) => a.name === id)?.avatar ?? null);
  const face = avatarIdFor(id, saved);
  return (
    <img
      src={avatarSrc(face)}
      alt=""
      aria-hidden
      width={size}
      height={size}
      data-avatar={face}
      className={cn("inline-block shrink-0 rounded-full", className)}
      style={{ width: size, height: size, background: avatarMeta(face).bg }}
      draggable={false}
    />
  );
}
