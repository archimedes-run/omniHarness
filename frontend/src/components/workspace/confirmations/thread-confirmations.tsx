"use client";

import type { Message } from "@langchain/langgraph-sdk";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef } from "react";

import {
  PENDING_CONFIRMATIONS_KEY,
  usePendingConfirmations,
} from "@/core/confirmations/hooks";
import type { PostedResult } from "@/core/confirmations/logic";
import { anchorActions } from "@/core/messages/agents";

import { PendingConfirmations } from "./pending-confirmations";
import { AppCardStack, useThreadAppCards } from "./thread-app-approvals";

/**
 * A chat's confirmation cards, each IN the thread at the point it was raised
 * (Chat.dc.html): after the group of messages that names the action (its
 * stated plan, or the result of the agent that stopped to ask). An action no
 * message names yet is shown after the last message, as before.
 */
export function useThreadConfirmations(
  threadId: string,
  messages: Message[],
  enabled: boolean,
  running = false,
  onContinue?: (agent: string, actionId: string) => void,
  onResumed?: (runId: string) => void,
  onPickUp?: (actionIds: string[]) => Promise<Record<string, PostedResult>>,
) {
  const { pending } = usePendingConfirmations();
  // A run that just finished may have stated a plan: read the pending set
  // NOW, not at the next poll, so its card appears with the reply.
  const queryClient = useQueryClient();
  const wasRunning = useRef(running);
  useEffect(() => {
    if (wasRunning.current && !running) {
      void queryClient.invalidateQueries({
        queryKey: PENDING_CONFIRMATIONS_KEY,
      });
    }
    wasRunning.current = running;
  }, [running, queryClient]);
  const ids = useMemo(
    () =>
      (pending?.actions ?? [])
        .filter((action) => action.thread_id === threadId)
        .map((action) => action.id),
    [pending, threadId],
  );
  // STICKY: an action stays where it was raised after it resolves, so its
  // card keeps showing what happened (the pending set drops it at once).
  const sticky = useRef(new Map<string, string>());
  const anchored = useMemo(() => {
    for (const [id, index] of anchorActions(messages, ids)) {
      const key = messages[index]?.id ?? `index-${index}`;
      if (!sticky.current.has(id)) sticky.current.set(id, key);
    }
    return [...sticky.current.keys()];
  }, [messages, ids]);

  // Spec 011: app cards, each after the turn that registered its version.
  const appCards = useThreadAppCards(threadId, messages);

  const afterGroup = useCallback(
    (group: Message[]) => {
      if (!enabled) return null;
      const keys = new Set(
        group.map(
          (message) => message.id ?? `index-${messages.indexOf(message)}`,
        ),
      );
      const here = anchored.filter((id) =>
        keys.has(sticky.current.get(id) ?? ""),
      );
      const cards = [...keys].flatMap((k) => appCards.placed.get(k) ?? []);
      if (here.length === 0 && cards.length === 0) return null;
      return (
        <>
          {here.length > 0 && (
            <div
              className="-mt-4 w-full pl-[42px]"
              data-testid="inline-confirmations"
            >
              <PendingConfirmations
                threadId={threadId}
                only={here}
                quietWhenEmpty
                onContinue={onContinue}
                onResumed={onResumed}
                onPickUp={onPickUp}
              />
            </div>
          )}
          {cards.length > 0 && (
            <div className="-mt-4 w-full pl-[42px]">
              <AppCardStack
                cards={cards}
                wordsOf={appCards.wordsOf}
                testId="inline-app-cards"
              />
            </div>
          )}
        </>
      );
    },
    [
      anchored,
      appCards,
      enabled,
      messages,
      onContinue,
      onResumed,
      onPickUp,
      threadId,
    ],
  );

  const footer = enabled ? (
    <>
      <PendingConfirmations
        threadId={threadId}
        exclude={anchored}
        quietWhenEmpty
        onContinue={onContinue}
        onResumed={onResumed}
        onPickUp={onPickUp}
      />
      {/* Spec 011: app cards no turn names yet (button only), oldest first. */}
      <AppCardStack cards={appCards.rest} wordsOf={appCards.wordsOf} />
    </>
  ) : null;

  return { afterGroup, footer };
}
