"use client";

import type { Message } from "@langchain/langgraph-sdk";
import { ChevronDownIcon, LayoutGridIcon } from "lucide-react";
import { useMemo, useState } from "react";

import type { ApprovalCard } from "@/core/apps/api";
import { useApps, useThreadApprovals } from "@/core/apps/hooks";
import {
  anchorCards,
  cardWords,
  orderCards,
  type CardWords,
} from "@/core/apps/version-cards";
import { cn } from "@/lib/utils";

import { AppApprovalCard } from "./app-approval-card";

function textOf(message: Message): string {
  const content = message.content as unknown;
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content
      .map((p) =>
        typeof p === "string"
          ? p
          : typeof (p as { text?: unknown }).text === "string"
            ? (p as { text: string }).text
            : "",
      )
      .join(" ");
  }
  return "";
}

/**
 * Spec 011: the app cards raised in this chat, each placed right after the
 * turn whose job registered its version, oldest first (version-cards). The
 * newest undecided card is open; a decided or replaced one is one line with a
 * disclosure. Cards no turn names yet go at the end.
 */
export function useThreadAppCards(threadId: string, messages: Message[]) {
  const { data } = useThreadApprovals(threadId);
  const { apps } = useApps();
  return useMemo(() => {
    const cards = data ?? [];
    const { cards: ordered, newer, newestPending } = orderCards(cards);
    const served = new Map(
      (apps ?? []).map((a) => [a.id, a.current_version] as const),
    );
    const anchors = anchorCards(messages.map(textOf), ordered);
    const placed = new Map<string, ApprovalCard[]>();
    const rest: ApprovalCard[] = [];
    for (const card of ordered) {
      const index = anchors.get(card.id);
      const key =
        index === undefined ? null : (messages[index]?.id ?? `index-${index}`);
      if (key === null) rest.push(card);
      else placed.set(key, [...(placed.get(key) ?? []), card]);
    }
    const wordsOf = (card: ApprovalCard) =>
      cardWords(
        card,
        served.get(card.app_id),
        newer.get(card.id),
        card.id === newestPending,
      );
    return { placed, rest, wordsOf };
  }, [data, apps, messages]);
}

/** Cards for a group of messages (after its last named message), or the rest. */
export function AppCardStack({
  cards,
  wordsOf,
  testId = "thread-app-approvals",
}: {
  cards: ApprovalCard[];
  wordsOf: (card: ApprovalCard) => CardWords;
  testId?: string;
}) {
  if (cards.length === 0) return null;
  return (
    <div className="flex w-full flex-col gap-2" data-testid={testId}>
      {cards.map((card) => (
        <ThreadAppCard key={card.id} card={card} words={wordsOf(card)} />
      ))}
    </div>
  );
}

function ThreadAppCard({
  card,
  words,
}: {
  card: ApprovalCard;
  words: CardWords;
}) {
  const [open, setOpen] = useState(words.open);
  if (open) {
    return (
      <div className="flex w-full flex-col gap-1">
        {!words.open && (
          <button
            type="button"
            className="text-muted-foreground hover:text-foreground self-start text-xs"
            aria-expanded
            onClick={() => setOpen(false)}
          >
            Hide details
          </button>
        )}
        <AppApprovalCard card={card} words={words} reveal={words.open} />
      </div>
    );
  }
  return (
    <button
      type="button"
      onClick={() => setOpen(true)}
      aria-expanded={false}
      data-testid="app-card-line"
      data-card-id={card.id}
      data-state={words.state}
      className={cn(
        "border-border bg-card text-foreground hover:bg-accent flex w-full max-w-[640px] items-center gap-2 rounded-lg border px-3 py-2 text-left text-sm",
      )}
    >
      <LayoutGridIcon
        className="text-muted-foreground size-4 shrink-0"
        aria-hidden
      />
      <span className="min-w-0 flex-1 truncate">
        <span className="font-medium">{card.app_name}</span>
        {" · "}
        {words.line}
      </span>
      <ChevronDownIcon
        className="text-muted-foreground size-4 shrink-0"
        aria-hidden
      />
    </button>
  );
}
