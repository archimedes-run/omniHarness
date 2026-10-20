"use client";

import { useState } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  usePendingConfirmations,
  useEditConfirmation,
  useResolveConfirmation,
} from "@/core/confirmations/hooks";
import type { PendingAction, ResolveResult } from "@/core/confirmations/types";

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
}: {
  threadId?: string;
  quietWhenEmpty?: boolean;
  /** Only these actions: the cards raised at one point of a chat. */
  only?: string[];
  /** All but these: the cards not raised at a point the chat shows. */
  exclude?: string[];
  /** In a chat: "Continue <agent>" once a call it stopped for has run. */
  onContinue?: (agent: string, actionId: string) => void;
}) {
  const { pending, isLoading, error } = usePendingConfirmations();
  const resolve = useResolveConfirmation();
  const edit = useEditConfirmation();
  const [resolved, setResolved] = useState<
    Record<string, { result: ResolveResult; action: PendingAction }>
  >({});
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
        <p
          key={item.id}
          className="border-border text-muted-foreground rounded-md border px-3 py-2 text-sm"
          data-testid="awaiting-post"
        >
          Result waiting to post ·{" "}
          <span className="text-foreground">{item.tool_name}</span>, run for{" "}
          {item.requester}. It appears in the chat as soon as the chat is free.
        </p>
      ))}

      {pending?.readable && shown.length === 0 && awaiting.length === 0 && (
        <p className="text-muted-foreground text-sm" data-testid="empty">
          Nothing is waiting for your confirmation.
        </p>
      )}

      {shown.map((action) => (
        <PendingActionCard
          key={action.id}
          action={action}
          busy={resolve.isPending || edit.isPending}
          result={resolved[action.id]?.result}
          onContinue={onContinue}
          onEdit={(args, typedCount) =>
            edit.mutate(
              { id: action.id, args, typedCount },
              {
                onSuccess: (result) =>
                  setResolved((previous) => ({
                    ...previous,
                    [action.id]: { result, action },
                  })),
              },
            )
          }
          onResolve={(confirm, typedCount) =>
            resolve.mutate(
              { id: action.id, confirm, typedCount },
              {
                onSuccess: (result) =>
                  setResolved((previous) => ({
                    ...previous,
                    [action.id]: { result, action },
                  })),
              },
            )
          }
        />
      ))}
    </div>
  );
}
