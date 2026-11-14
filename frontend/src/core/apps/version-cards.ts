/**
 * App cards in a chat: where each goes, in what order, and what it says in
 * each state. Pure, so unit-tested apart from rendering.
 *
 * - Each card sits right after the assistant turn whose job registered its
 *   version: the job's report names the card ("card <id>") or, in reports
 *   from before that, "id <app>, version <n>". Cards with no such turn go at
 *   the end. Oldest first.
 * - Only the newest undecided card is open; a decided or replaced card is
 *   one line, with a disclosure.
 * - The words name the version actually served now, never a stale one.
 */
import type { ApprovalCard } from "./api";
import { atText } from "./wording";

/** Text cut at a word boundary, with an ellipsis, when longer than `max`. */
export function clipWords(text: string, max = 160): string {
  const flat = text.replace(/\s+/g, " ").trim();
  if (flat.length <= max) return flat;
  const cut = flat.slice(0, max + 1);
  const space = cut.lastIndexOf(" ");
  const head = (
    space > max * 0.5 ? cut.slice(0, space) : flat.slice(0, max)
  ).replace(/[\s,;:.\-–—]+$/, "");
  return `${head}…`;
}

/** The gateway's description cap; text this long was cut there (older
 * versions cut mid-word), so its last partial word is dropped. */
const DESCRIPTION_CAP = 300;

/** Where descriptions were cut before they were clipped at a word: the
 * job's title (80) and the version note (300). */
const STORAGE_LIMITS = [80, DESCRIPTION_CAP];

/** The assistant's description of a change, clipped at a word. Text that
 * ends without terminal punctuation at a storage limit was cut there, maybe
 * mid-word: its last partial word is dropped. */
export function clipDescription(text: string, max = 280): string {
  const flat = text.replace(/\s+/g, " ").trim();
  const cutAtLimit = STORAGE_LIMITS.some(
    (limit) => flat.length >= limit - 1 && flat.length <= limit,
  );
  if (cutAtLimit && !/[.!?…)"'’”]$/.test(flat)) {
    const space = flat.lastIndexOf(" ");
    return clipWords(
      `${flat.slice(0, space > 0 ? space : flat.length).replace(/[\s,;:.\-–—]+$/, "")}…`,
      max,
    );
  }
  return clipWords(flat, max);
}

const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** card id → index of the message (in `texts`) that registered it. */
export function anchorCards(
  texts: string[],
  cards: Pick<ApprovalCard, "id" | "app_id" | "version">[],
): Map<string, number> {
  const anchors = new Map<string, number>();
  for (const card of cards) {
    const byId = `card ${card.id}`;
    const byVersion = new RegExp(
      `App registered by the system: id ${escape(card.app_id)}, version ${card.version}(?!\\d)`,
    );
    for (let i = 0; i < texts.length; i++) {
      const text = texts[i] ?? "";
      if (text.includes(byId) || byVersion.test(text)) {
        anchors.set(card.id, i);
        break;
      }
    }
  }
  return anchors;
}

export type CardState = "pending" | "used" | "kept" | "replaced" | "allowed";

export interface CardWords {
  state: CardState;
  /** Open (the newest undecided card) or one line with a disclosure. */
  open: boolean;
  /** The one line shown when closed. */
  line: string;
  /** The state sentence shown when open. */
  sentence: string;
  /** The "reads the same data" sentence, naming the served version. */
  sameData: string;
  /** The version Keep keeps: the one served now while undecided, else the
   * card's record of it. */
  keeps: number;
}

/**
 * The words of one card. `served`: the version the app serves now (unknown:
 * the card's own record of it). `newer`: the next card's version for the same
 * app in this chat, if any. `newestPending`: whether this is the newest
 * undecided card in the chat.
 */
function wordsFor(
  card: Pick<
    ApprovalCard,
    "kind" | "status" | "version" | "keeps_version" | "resolved_at" | "app_name"
  >,
  served: number | undefined,
  newer: number | undefined,
  newestPending: boolean,
): Omit<CardWords, "keeps"> {
  const keeps = card.keeps_version ?? Math.max(1, card.version - 1);
  const now = served ?? keeps;
  const v = card.version;
  const replaced = (by: number | undefined) => ({
    state: "replaced" as const,
    open: false,
    line: `Version ${v} — replaced by version ${by ?? now}`,
    sentence: `Replaced by version ${by ?? now}.`,
    sameData: `It reads the same data as version ${keeps}.`,
  });
  if (card.kind !== "version") {
    if (card.status === "pending") {
      return {
        state: "pending",
        open: newestPending,
        line: `${card.app_name}: app access, waiting for you`,
        sentence: "",
        sameData: "",
      };
    }
    if (card.status === "approved") {
      return {
        state: "allowed",
        open: false,
        line: `${card.app_name}: app access allowed${card.resolved_at ? ` ${atText(card.resolved_at)}` : ""}`,
        sentence: "Allowed.",
        sameData: "",
      };
    }
    return { ...replaced(newer), sameData: "" };
  }
  if (card.status === "pending") {
    return {
      state: "pending",
      open: newestPending,
      line: `Version ${v} — waiting for you`,
      sentence: `Version ${now} keeps running until you choose.`,
      sameData: `It reads the same data as version ${now}, the version you use now.`,
    };
  }
  if (card.status === "kept") {
    return {
      state: "kept",
      open: false,
      line: `Kept version ${keeps}`,
      sentence: `You kept version ${keeps}.`,
      sameData: `It reads the same data as version ${keeps}.`,
    };
  }
  if (card.status === "approved" && (served === undefined || served === v)) {
    const since = card.resolved_at ? atText(card.resolved_at) : "";
    return {
      state: "used",
      open: false,
      line: since
        ? `Version ${v} — in use since ${since}`
        : `Version ${v} — in use`,
      sentence: `${since ? `In use since ${since}.` : "In use."} Version ${keeps} is in History.`,
      sameData: `It reads the same data as version ${keeps}.`,
    };
  }
  // Superseded before a decision, or used and then replaced since.
  return replaced(newer ?? (served !== v ? served : undefined));
}

export function cardWords(
  card: Parameters<typeof wordsFor>[0],
  served: number | undefined,
  newer: number | undefined,
  newestPending: boolean,
): CardWords {
  const record = card.keeps_version ?? Math.max(1, card.version - 1);
  return {
    ...wordsFor(card, served, newer, newestPending),
    keeps: card.status === "pending" ? (served ?? record) : record,
  };
}

/** Oldest first; for each card, the next card's version of the same app. */
export function orderCards<
  C extends Pick<
    ApprovalCard,
    "id" | "app_id" | "version" | "created_at" | "status"
  >,
>(
  cards: C[],
): { cards: C[]; newer: Map<string, number>; newestPending: string | null } {
  const sorted = [...cards].sort(
    (a, b) =>
      Date.parse(a.created_at) - Date.parse(b.created_at) ||
      a.version - b.version,
  );
  const newer = new Map<string, number>();
  sorted.forEach((card, i) => {
    const next = sorted.slice(i + 1).find((c) => c.app_id === card.app_id);
    if (next) newer.set(card.id, next.version);
  });
  const pending = sorted.filter((c) => c.status === "pending");
  return {
    cards: sorted,
    newer,
    newestPending: pending.length ? pending[pending.length - 1]!.id : null,
  };
}

/** What placement needs to know of one thread message. */
export interface MessageFacts {
  text: string;
  /** A tool result: the id of the call it answers. */
  toolCallId?: string;
  /** The result of a coding job (where versions are registered). */
  isJobResult: boolean;
  /** The person's own words, when this is a genuine (server-marked) user
   * turn; null otherwise. */
  userText: string | null;
}

/** A coding job's registration, as its job record says (by tool call). */
export interface JobRegistration {
  app_id: string;
  version: number;
}

/**
 * card id → index of the message it follows. In order: the turn whose report
 * names the card or its version; the job (by tool call) whose record says it
 * registered that version; else by time against the cards that were placed:
 * the job result before the next placed card, or that card's turn, or the
 * last placed earlier card's turn. Only a card with nothing placed around it
 * is left out (the end of the thread).
 */
export function placeCards(
  messages: MessageFacts[],
  cards: Pick<ApprovalCard, "id" | "app_id" | "version" | "created_at">[],
  registrations: Map<string, JobRegistration[]>,
): Map<string, number> {
  const anchors = anchorCards(
    messages.map((m) => m.text),
    cards,
  );
  for (const card of cards) {
    if (anchors.has(card.id)) continue;
    const index = messages.findIndex(
      (m) =>
        m.toolCallId !== undefined &&
        (registrations.get(m.toolCallId) ?? []).some(
          (r) => r.app_id === card.app_id && r.version === card.version,
        ),
    );
    if (index !== -1) anchors.set(card.id, index);
  }
  const time = (c: { created_at: string }) => Date.parse(c.created_at) || 0;
  const placed = cards.filter((c) => anchors.has(c.id));
  for (const card of cards) {
    if (anchors.has(card.id)) continue;
    const later = placed
      .filter((c) => time(c) > time(card))
      .sort((a, b) => time(a) - time(b))[0];
    if (later) {
      const at = anchors.get(later.id)!;
      let before = -1;
      for (let i = at - 1; i >= 0; i--) {
        if (messages[i]?.isJobResult) {
          before = i;
          break;
        }
      }
      anchors.set(card.id, before !== -1 ? before : at);
      continue;
    }
    const earlier = placed
      .filter((c) => time(c) <= time(card))
      .sort((a, b) => time(b) - time(a))[0];
    if (earlier) anchors.set(card.id, anchors.get(earlier.id)!);
  }
  return anchors;
}

/** The person's own words that started the turn ending at `index`. */
export function requestBefore(
  messages: MessageFacts[],
  index: number,
): string | null {
  for (let i = index; i >= 0; i--) {
    const words = messages[i]?.userText;
    if (words) return words;
  }
  return null;
}

export type RegistrationState =
  | { kind: "in_use" }
  | { kind: "offered" }
  | { kind: "replaced"; by: number }
  | { kind: "kept"; version: number }
  | { kind: "needs_approval" }
  | { kind: "unknown" };

/**
 * The live state of a version a job registered, from the app's served
 * version and this chat's cards (data the chat already reads).
 */
export function registrationState(
  appId: string,
  version: number,
  served: number | undefined,
  cards: Pick<
    ApprovalCard,
    "app_id" | "version" | "status" | "keeps_version" | "kind"
  >[],
  needsApproval: boolean,
): RegistrationState {
  const own = cards.find((c) => c.app_id === appId && c.version === version);
  if (served === version) return { kind: "in_use" };
  if (own?.status === "pending") {
    return own.kind === "version"
      ? { kind: "offered" }
      : { kind: "needs_approval" };
  }
  if (own?.status === "kept") {
    return {
      kind: "kept",
      version: own.keeps_version ?? served ?? version - 1,
    };
  }
  const newer = cards
    .filter((c) => c.app_id === appId && c.version > version)
    .sort((a, b) => a.version - b.version)[0];
  if (served !== undefined && served > version) {
    return { kind: "replaced", by: served };
  }
  if (own?.status === "superseded" && newer) {
    return { kind: "replaced", by: newer.version };
  }
  if (served === undefined && !own) {
    return needsApproval ? { kind: "needs_approval" } : { kind: "unknown" };
  }
  return { kind: "unknown" };
}

export function registrationWords(state: RegistrationState): string {
  switch (state.kind) {
    case "in_use":
      return "in use";
    case "offered":
      return "offered — waiting for your choice";
    case "replaced":
      return `replaced by version ${state.by}`;
    case "kept":
      return `kept version ${state.version}`;
    case "needs_approval":
      return "needs your approval";
    case "unknown":
      return "";
  }
}
