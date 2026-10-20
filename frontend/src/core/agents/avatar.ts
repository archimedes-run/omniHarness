/**
 * Which avatar colour an agent gets (Feature 006).
 *
 * Deterministic from the agent's id, so an agent has the same colour on every
 * page, in every session, for every user: a 32-bit FNV-1a hash of the id,
 * modulo the palette size. The lead agent always gets its own fixed colour.
 * An @mention of an agent takes the same colour as its avatar.
 *
 * Colour is never the only identifier: avatars always show initials, and
 * mentions always show the name.
 */

/** The lead agent's id (the LangGraph assistant id). */
export const LEAD_AGENT_ID = "lead_agent";

export const AVATAR_PALETTE_SIZE = 8;

export type AvatarColor = "lead" | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7;

/** Stable 32-bit FNV-1a hash of a string. */
function hash(text: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h >>> 0;
}

export function avatarColor(agentId: string): AvatarColor {
  const id = agentId.trim();
  if (id === LEAD_AGENT_ID || id === "lead") return "lead";
  return (hash(id.toLowerCase()) % AVATAR_PALETTE_SIZE) as AvatarColor;
}

/**
 * Literal class names, so Tailwind generates them (it cannot see a class
 * built at runtime from `bg-avatar-${n}`).
 */
const CLASSES: Record<AvatarColor, { avatar: string; mention: string }> = {
  lead: {
    avatar: "bg-avatar-lead text-avatar-lead-foreground",
    mention: "text-avatar-lead-foreground",
  },
  0: {
    avatar: "bg-avatar-0 text-avatar-0-foreground",
    mention: "text-avatar-0-foreground",
  },
  1: {
    avatar: "bg-avatar-1 text-avatar-1-foreground",
    mention: "text-avatar-1-foreground",
  },
  2: {
    avatar: "bg-avatar-2 text-avatar-2-foreground",
    mention: "text-avatar-2-foreground",
  },
  3: {
    avatar: "bg-avatar-3 text-avatar-3-foreground",
    mention: "text-avatar-3-foreground",
  },
  4: {
    avatar: "bg-avatar-4 text-avatar-4-foreground",
    mention: "text-avatar-4-foreground",
  },
  5: {
    avatar: "bg-avatar-5 text-avatar-5-foreground",
    mention: "text-avatar-5-foreground",
  },
  6: {
    avatar: "bg-avatar-6 text-avatar-6-foreground",
    mention: "text-avatar-6-foreground",
  },
  7: {
    avatar: "bg-avatar-7 text-avatar-7-foreground",
    mention: "text-avatar-7-foreground",
  },
};

/** Fill and text classes for an agent's avatar (initials go inside it). */
export function avatarClasses(agentId: string): string {
  return CLASSES[avatarColor(agentId)].avatar;
}

/** Text class for an @mention of the agent: the colour of its avatar. */
export function mentionClasses(agentId: string): string {
  return CLASSES[avatarColor(agentId)].mention;
}

/** Up to two initials from an agent's name, e.g. "Release manager" -> "RM". */
export function avatarInitials(name: string): string {
  const words = name.replace(/[_-]+/g, " ").trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return "?";
  const letters =
    words.length === 1
      ? words[0]!.slice(0, 2)
      : words[0]![0]! + words[words.length - 1]![0]!;
  return letters.toUpperCase();
}
