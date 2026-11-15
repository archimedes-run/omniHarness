"use client";

import type { Message } from "@langchain/langgraph-sdk";
import { useQueries } from "@tanstack/react-query";
import { ChevronDownIcon, LayoutGridIcon } from "lucide-react";
import { useMemo, useState } from "react";

import type { ApprovalCard } from "@/core/apps/api";
import { useApps, useThreadApprovals } from "@/core/apps/hooks";
import {
  cardWords,
  orderCards,
  placeCards,
  requestBefore,
  type CardWords,
  type JobRegistration,
  type MessageFacts,
} from "@/core/apps/version-cards";
import type { CodeJobPayload } from "@/core/code-jobs/api";
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

/** The server's mark on a human message that IS the person's turn
 * (omniharness/agents/turns.py USER_TURN_MARKER). */
const USER_TURN_MARKER = "omniharness_user_turn";

function factsOf(message: Message): MessageFacts {
  const m = message as Message & {
    tool_call_id?: string;
    name?: string;
    additional_kwargs?: Record<string, unknown>;
  };
  const isUser =
    m.type === "human" && m.additional_kwargs?.[USER_TURN_MARKER] === true;
  return {
    text: textOf(message),
    toolCallId: m.type === "tool" ? m.tool_call_id : undefined,
    isJobResult: m.type === "tool" && m.name === "code_job",
    userText: isUser
      ? textOf(message).replace(/\s+/g, " ").trim() || null
      : null,
  };
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
  // What each coding job registered, read from the job cards' own queries
  // (cache only: nothing more is fetched or polled for this).
  const callIds = useMemo(
    () =>
      messages.flatMap((m) => {
        const t = m as Message & { tool_call_id?: string; name?: string };
        return t.type === "tool" && t.name === "code_job" && t.tool_call_id
          ? [t.tool_call_id]
          : [];
      }),
    [messages],
  );
  const jobs = useQueries({
    queries: callIds.map((id) => ({
      queryKey: ["code-job", threadId, id],
      enabled: false,
    })),
  });
  const jobsStamp = jobs.map((q) => q.dataUpdatedAt).join();
  const registrations = useMemo(() => {
    const out = new Map<string, JobRegistration[]>();
    jobs.forEach((q, i) => {
      const payload = q.data as CodeJobPayload | undefined;
      if (!payload) return;
      const found: JobRegistration[] = [];
      const reg = payload.job.result?.app_registration;
      if (reg) found.push({ app_id: reg.app_id, version: reg.version });
      for (const step of payload.steps) {
        if (step.kind === "app_registered") {
          found.push({ app_id: step.app_id, version: step.version });
        }
      }
      out.set(callIds[i]!, found);
    });
    return out;
    // `jobsStamp` changes when a job record does; `jobs` is a new array each render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [callIds, jobsStamp]);
  return useMemo(() => {
    const cards = data ?? [];
    const { cards: ordered, newer, newestPending } = orderCards(cards);
    const served = new Map(
      (apps ?? []).map((a) => [a.id, a.current_version] as const),
    );
    const facts = messages.map(factsOf);
    const anchors = placeCards(facts, ordered, registrations);
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
    // Cards from before the server kept the request: the person's own words
    // that started the turn the card follows.
    const requestOf = (card: ApprovalCard) => {
      if (card.request_words || card.suggestion) return null;
      const index = anchors.get(card.id);
      return index === undefined ? null : requestBefore(facts, index);
    };
    return { placed, rest, wordsOf, requestOf };
  }, [data, apps, messages, registrations]);
}

/** Cards for a group of messages (after its last named message), or the rest. */
export function AppCardStack({
  cards,
  wordsOf,
  requestOf,
  testId = "thread-app-approvals",
}: {
  cards: ApprovalCard[];
  wordsOf: (card: ApprovalCard) => CardWords;
  requestOf?: (card: ApprovalCard) => string | null;
  testId?: string;
}) {
  if (cards.length === 0) return null;
  return (
    <div className="flex w-full flex-col gap-2" data-testid={testId}>
      {cards.map((card) => (
        <ThreadAppCard
          key={card.id}
          card={card}
          words={wordsOf(card)}
          request={requestOf?.(card) ?? null}
        />
      ))}
    </div>
  );
}

function ThreadAppCard({
  card,
  words,
  request,
}: {
  card: ApprovalCard;
  words: CardWords;
  request: string | null;
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
        <AppApprovalCard
          card={card}
          words={words}
          reveal={words.open}
          request={request}
        />
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
