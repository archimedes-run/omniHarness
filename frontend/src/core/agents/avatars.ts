/**
 * The faces an agent can wear (006-G, Agent & Skill Studio).
 *
 * Twenty self-contained SVGs in public/avatars/<id>.svg. An agent saves the id
 * of one (`Agent.avatar`, validated server-side against the same twenty); an
 * agent saved before 006-G has none and shows a stable default picked from its
 * name, so it looks the same everywhere and on every visit. The lead agent is
 * always Merlo.
 *
 * Only ids from this list ever reach an <img src>: whatever a record says, an
 * unknown value falls back to the default, so no stored string can name any
 * other path.
 */

import { LEAD_AGENT_ID } from "./avatar";

export interface AvatarMeta {
  id: string;
  name: string;
  /** One word: its personality. */
  tag: string;
  /** Its disc colour (the SVG paints it too; used behind it while it loads). */
  bg: string;
  blurb: string;
}

export const AVATARS: readonly AvatarMeta[] = [
  {
    id: "pip",
    name: "Pip",
    tag: "Sleuth",
    bg: "#2C69AD",
    blurb: "Finds the one detail everyone missed.",
  },
  {
    id: "blitz",
    name: "Blitz",
    tag: "Hype",
    bg: "#C02B2B",
    blurb: "Celebrates every tiny win. Loudly.",
  },
  {
    id: "lotus",
    name: "Lotus",
    tag: "Zen",
    bg: "#23826B",
    blurb: "Unbothered. Breathes in deadlines, breathes out plans.",
  },
  {
    id: "zap",
    name: "Zap",
    tag: "Chaos",
    bg: "#8A46C8",
    blurb: "Tries ten things at once. Seven work.",
  },
  {
    id: "grumbo",
    name: "Grumbo",
    tag: "Grump",
    bg: "#55657C",
    blurb: "Hates meetings. Loves a clean inbox.",
  },
  {
    id: "dex",
    name: "Dex",
    tag: "Nerd",
    bg: "#8A6A00",
    blurb: "Has read the docs. All of them.",
  },
  {
    id: "duchess",
    name: "Duchess",
    tag: "Diva",
    bg: "#BE2E80",
    blurb: "Makes every status report a red-carpet moment.",
  },
  {
    id: "snooze",
    name: "Snooze",
    tag: "Sleepy",
    bg: "#4C5ED2",
    blurb: "Works the night shift so you don't have to.",
  },
  {
    id: "boost",
    name: "Boost",
    tag: "Eager",
    bg: "#C2470A",
    blurb: "Already started before you finished asking.",
  },
  {
    id: "merlo",
    name: "Merlo",
    tag: "Wise",
    bg: "#7052DC",
    blurb: "Speaks in summaries. Occasionally in riddles.",
  },
  {
    id: "barnacle",
    name: "Barnacle",
    tag: "Rogue",
    bg: "#136C93",
    blurb: "Plunders your backlog for quick wins.",
  },
  {
    id: "wub",
    name: "Wub",
    tag: "Groovy",
    bg: "#9A2FB0",
    blurb: "Keeps the tempo. Your standups have never flowed better.",
  },
  {
    id: "basil",
    name: "Basil",
    tag: "Fussy",
    bg: "#5E7A12",
    blurb: "Every output plated just so.",
  },
  {
    id: "shade",
    name: "Shade",
    tag: "Stealthy",
    bg: "#2C7A44",
    blurb: "Gets it done before you notice it started.",
  },
  {
    id: "blip",
    name: "Blip",
    tag: "Curious",
    bg: "#BA2E54",
    blurb: "Asks the follow-up question you forgot.",
  },
  {
    id: "bolt",
    name: "Bolt",
    tag: "Literal",
    bg: "#9C5628",
    blurb: "Does exactly what you said. Exactly.",
  },
  {
    id: "boo",
    name: "Boo",
    tag: "Shy",
    bg: "#4560CC",
    blurb: "Quietly fixes things. Won't take credit.",
  },
  {
    id: "mochi",
    name: "Mochi",
    tag: "Smug",
    bg: "#2F7480",
    blurb: "Knew the answer. Waited for you to ask.",
  },
  {
    id: "croak",
    name: "Croak",
    tag: "Chill",
    bg: "#B23E76",
    blurb: "Nothing is urgent until it is. Then it's handled.",
  },
  {
    id: "inky",
    name: "Inky",
    tag: "Multitasker",
    bg: "#0E6F7E",
    blurb: "Eight arms, eight open threads, zero dropped.",
  },
];

/** The lead agent's face, always. */
export const LEAD_AVATAR = "merlo";

const BY_ID = new Map(AVATARS.map((a) => [a.id, a]));

export function isAvatarId(value: unknown): value is string {
  return typeof value === "string" && BY_ID.has(value);
}

/** Stable 32-bit FNV-1a hash (the same one the old colour avatars used). */
function hash(text: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h >>> 0;
}

/** The avatar an agent shows: its saved one, Merlo for the lead, else a
 * stable default from its id. */
export function avatarIdFor(agentId: string, saved?: string | null): string {
  const id = agentId.trim();
  if (id === LEAD_AGENT_ID || id === "lead") return LEAD_AVATAR;
  if (isAvatarId(saved)) return saved;
  return AVATARS[hash(id.toLowerCase()) % AVATARS.length]!.id;
}

export function avatarMeta(id: string): AvatarMeta {
  return BY_ID.get(id) ?? BY_ID.get(LEAD_AVATAR)!;
}

/** The image URL for a KNOWN avatar id (anything else: the lead's). */
export function avatarSrc(id: string): string {
  return `/avatars/${isAvatarId(id) ? id : LEAD_AVATAR}.svg`;
}

/** A random avatar, never `current` (Surprise me). */
export function randomAvatar(
  current?: string | null,
  rand: () => number = Math.random,
): string {
  const pool = AVATARS.filter((a) => a.id !== current);
  return pool[Math.floor(rand() * pool.length) % pool.length]!.id;
}
