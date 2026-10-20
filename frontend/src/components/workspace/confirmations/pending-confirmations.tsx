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
}: {
  threadId?: string;
  quietWhenEmpty?: boolean;
}) {
  const { pending, isLoading, error } = usePendingConfirmations();
  const resolve = useResolveConfirmation();
  const edit = useEditConfirmation();
  const [resolved, setResolved] = useState<
    Record<string, { result: ResolveResult; action: PendingAction }>
  >({});
  const actions = (pending?.actions ?? []).filter(
    (a) => threadId == null || a.thread_id === threadId,
  );
  // An action resolved here stays on screen with its result until it drops
  // out of the pending set on the next read.
  const shown = [
    ...actions,
    ...Object.values(resolved)
      .map((r) => r.action)
      .filter((a) => !actions.some((p) => p.id === a.id)),
  ];

  if (quietWhenEmpty && pending?.readable && shown.length === 0) return null;

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

      {pending?.readable && shown.length === 0 && (
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
