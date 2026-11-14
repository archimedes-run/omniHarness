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

/** The assistant's description of a change, clipped at a word. */
export function clipDescription(text: string, max = 280): string {
  const flat = text.replace(/\s+/g, " ").trim();
  if (flat.length >= DESCRIPTION_CAP - 1 && !flat.endsWith("…")) {
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
      `App registered by the system: id ${escape(card.app_id)}, version ${card.version}[;( ]`,
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
