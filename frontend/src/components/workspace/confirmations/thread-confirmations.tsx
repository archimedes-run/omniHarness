"use client";

import type { Message } from "@langchain/langgraph-sdk";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef } from "react";

import {
  PENDING_CONFIRMATIONS_KEY,
  usePendingConfirmations,
} from "@/core/confirmations/hooks";
import { anchorActions } from "@/core/messages/agents";

import { PendingConfirmations } from "./pending-confirmations";

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
  onPickUp?: (actionId: string) => Promise<boolean>,
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

  const afterGroup = useCallback(
    (group: Message[]) => {
      if (!enabled || anchored.length === 0) return null;
      const keys = new Set(
        group.map(
          (message) => message.id ?? `index-${messages.indexOf(message)}`,
        ),
      );
      const here = anchored.filter((id) =>
        keys.has(sticky.current.get(id) ?? ""),
      );
      if (here.length === 0) return null;
      return (
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
      );
    },
    [anchored, enabled, messages, onContinue, onResumed, onPickUp, threadId],
  );

  const footer = enabled ? (
    <PendingConfirmations
      threadId={threadId}
      exclude={anchored}
      quietWhenEmpty
      onContinue={onContinue}
      onResumed={onResumed}
      onPickUp={onPickUp}
    />
  ) : null;

  return { afterGroup, footer };
}
