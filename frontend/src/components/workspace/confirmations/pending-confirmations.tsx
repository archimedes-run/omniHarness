"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { applyAll, resumeRunId } from "@/core/confirmations/api";
import {
  PENDING_CONFIRMATIONS_KEY,
  usePendingConfirmations,
  useEditConfirmation,
  useResolveConfirmation,
} from "@/core/confirmations/hooks";
import {
  groupOutbound,
  isRunning,
  RUNNING_PICKUP_INTERVAL_MS,
  RUNNING_PICKUP_MAX_TRIES,
} from "@/core/confirmations/logic";
import type { PendingAction, ResolveResult } from "@/core/confirmations/types";

import { ApplyAllBar } from "./apply-all-bar";
import { OutboundGroupCard } from "./outbound-group-card";
import { PendingActionCard } from "./pending-action-card";

/**
 * Pending Tier 3 actions, with Confirm and Decline (Phase 2.5).
 *
 * The ONE implementation: the Inbox shows every pending action, a chat thread
 * shows the ones that thread produced (`threadId`). Both resolve through the
 * same route, and so through confirm_flow, the single confirmation path.
 *
 * FR-008 holds in both places: "I cannot tell what is pending" is shown as
 * such, never as an empty list. `quietWhenEmpty` (the chat thread) renders
 * nothing when the set was read and is empty: a card per thread is noise when
 * there is nothing to decide.
 */
export function PendingConfirmations({
  threadId,
  quietWhenEmpty = false,
  only,
  exclude,
  onContinue,
  onResumed,
  onPickUp,
}: {
  threadId?: string;
  quietWhenEmpty?: boolean;
  /** Only these actions: the cards raised at one point of a chat. */
  only?: string[];
  /** All but these: the cards not raised at a point the chat shows. */
  exclude?: string[];
  /** In a chat: "Continue <agent>" once a call it stopped for has run. */
  onContinue?: (agent: string, actionId: string) => void;
  /** In a chat: the lead carries on after a turn's outbound calls were
   *  answered (Feature 007); the chat joins that run to show it. */
  onResumed?: (runId: string) => void;
  /** In a chat: look for a running call's posted result, and show it in the
   *  chat if it has landed (true). */
  onPickUp?: (actionId: string) => Promise<boolean>;
}) {
  const { pending, isLoading, error } = usePendingConfirmations();
  const resolve = useResolveConfirmation();
  const edit = useEditConfirmation();
  const queryClient = useQueryClient();
  const [resolved, setResolved] = useState<
    Record<string, { result: ResolveResult; action: PendingAction }>
  >({});
  const [applying, setApplying] = useState<string | null>(null);
  const [applyErrors, setApplyErrors] = useState<Record<string, string>>({});

  // A call confirmed here that is still running: its result is posted into
  // the chat when it finishes. Look for it on a bounded schedule, and once
  // it has landed say so on the card.
  const pickUp = useRef(onPickUp);
  pickUp.current = onPickUp;
  const running = Object.values(resolved)
    .filter((r) => isRunning(r.result) && r.result.detail?.landed !== true)
    .map((r) => r.action.id)
    .sort()
    .join(",");
  useEffect(() => {
    if (!running || !pickUp.current) return;
    const ids = running.split(",");
    let tries = 0;
    let stopped = false;
    const timer = setInterval(() => {
      tries += 1;
      if (tries >= RUNNING_PICKUP_MAX_TRIES) clearInterval(timer);
      for (const id of ids) {
        void pickUp
          .current?.(id)
          .then((landed) => {
            if (!landed || stopped) return;
            setResolved((previous) => {
              const entry = previous[id];
              if (!entry) return previous;
              return {
                ...previous,
                [id]: {
                  ...entry,
                  result: {
                    ...entry.result,
                    detail: { ...entry.result.detail, landed: true },
                  },
                },
              };
            });
            void queryClient.invalidateQueries({
              queryKey: PENDING_CONFIRMATIONS_KEY,
            });
          })
          .catch(() => undefined);
      }
    }, RUNNING_PICKUP_INTERVAL_MS);
    return () => {
      stopped = true;
      clearInterval(timer);
    };
  }, [running, queryClient]);

  const settle = (action: PendingAction, result: ResolveResult) => {
    setResolved((previous) => ({
      ...previous,
      [action.id]: { result, action },
    }));
    const runId = resumeRunId(result.detail);
    if (runId) onResumed?.(runId);
  };

  async function applyGroup(
    group: string,
    members: PendingAction[],
    ids: string[],
  ) {
    setApplying(group);
    setApplyErrors((previous) => ({ ...previous, [group]: "" }));
    try {
      const out = await applyAll(ids);
      const byId = new Map(members.map((a) => [a.id, a]));
      setResolved((previous) => {
        const next = { ...previous };
        for (const result of out.results) {
          const action = result.action_id ? byId.get(result.action_id) : null;
          if (action) next[action.id] = { result, action };
        }
        return next;
      });
      if (out.resume_run_id) onResumed?.(out.resume_run_id);
    } catch (e) {
      setApplyErrors((previous) => ({
        ...previous,
        [group]: e instanceof Error ? e.message : String(e),
      }));
    } finally {
      setApplying(null);
      void queryClient.invalidateQueries({
        queryKey: PENDING_CONFIRMATIONS_KEY,
      });
    }
  }
  const actions = (pending?.actions ?? []).filter(
    (a) =>
      (threadId == null || a.thread_id === threadId) &&
      (only?.includes(a.id) ?? true) &&
      !exclude?.includes(a.id),
  );
  // An action resolved here stays on screen with its result until it drops
  // out of the pending set on the next read.
  const shown = [
    ...actions,
    ...Object.values(resolved)
      .map((r) => r.action)
      .filter((a) => !actions.some((p) => p.id === a.id)),
  ];

  // Results that ran and are not yet in their chat. Shown once, where the
  // chat's unanchored cards go (never in an `only` group), and not for a card
  // still on screen here, which says so itself.
  const awaiting =
    only == null
      ? (pending?.awaiting_post ?? []).filter(
          (a) =>
            (threadId == null || a.thread_id === threadId) &&
            !(a.id in resolved),
        )
      : [];

  if (
    quietWhenEmpty &&
    pending?.readable &&
    shown.length === 0 &&
    awaiting.length === 0
  )
    return null;

  return (
    <div className="space-y-3" data-testid="pending-confirmations">
      {isLoading && !quietWhenEmpty && (
        <p className="text-muted-foreground text-sm">Loading…</p>
      )}

      {(error != null || pending?.readable === false) && (
        <Alert variant="destructive" data-testid="unreadable">
          <AlertTitle>I cannot tell what is pending</AlertTitle>
          <AlertDescription>
            The pending set could not be read, so this list may be missing
            actions rather than empty. {pending?.error ?? String(error ?? "")}
          </AlertDescription>
        </Alert>
      )}

      {awaiting.map((item) => (
        <div
          key={item.id}
          className="border-border text-muted-foreground rounded-md border px-3 py-2 text-sm"
          data-testid="awaiting-post"
          data-post-state={item.post_state ?? "waiting"}
        >
          <p>
            {item.post_state === "failed"
              ? "Result could not be posted to the chat"
              : item.post_state === "dropped"
                ? "Chat deleted; result kept here"
                : "Result waiting to post"}{" "}
            · <span className="text-foreground">{item.tool_name}</span>, run for{" "}
            {item.requester}.
            {(item.post_state ?? "waiting") === "waiting" &&
              " It appears in the chat as soon as the chat is free."}
          </p>
          {item.result && (
            <p className="text-foreground mt-1 whitespace-pre-wrap">
              {item.result}
            </p>
          )}
        </div>
      ))}

      {pending?.readable && shown.length === 0 && awaiting.length === 0 && (
        <p className="text-muted-foreground text-sm" data-testid="empty">
          Nothing is waiting for your confirmation.
        </p>
      )}

      <ApplyAllBar actions={actions} />

      {groupOutbound(shown).map((entry) =>
        entry.kind === "group" ? (
          <OutboundGroupCard
            key={`group-${entry.group}`}
            actions={entry.actions}
            results={Object.fromEntries(
              entry.actions.map((a) => [a.id, resolved[a.id]?.result]),
            )}
            busy={resolve.isPending || edit.isPending}
            applying={applying === entry.group}
            applyError={applyErrors[entry.group]}
            onDecline={(id) => {
              const action = entry.actions.find((a) => a.id === id)!;
              resolve.mutate(
                { id, confirm: false },
                { onSuccess: (result) => settle(action, result) },
              );
            }}
            onApplyAll={(ids) =>
              void applyGroup(entry.group, entry.actions, ids)
            }
          />
        ) : (
          <PendingActionCard
            key={entry.action.id}
            action={entry.action}
            busy={resolve.isPending || edit.isPending}
            result={resolved[entry.action.id]?.result}
            onContinue={onContinue}
            onEdit={(args, typedCount) =>
              edit.mutate(
                { id: entry.action.id, args, typedCount },
                { onSuccess: (result) => settle(entry.action, result) },
              )
            }
            onResolve={(confirm, typedCount) =>
              resolve.mutate(
                { id: entry.action.id, confirm, typedCount },
                { onSuccess: (result) => settle(entry.action, result) },
              )
            }
          />
        ),
      )}
    </div>
  );
}
