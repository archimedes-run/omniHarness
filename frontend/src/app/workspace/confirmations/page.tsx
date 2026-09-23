"use client";

import { useState } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { PendingActionCard } from "@/components/workspace/confirmations/pending-action-card";
import {
  usePendingConfirmations,
  useResolveConfirmation,
} from "@/core/confirmations/hooks";
import type { ResolveResult } from "@/core/confirmations/types";

export default function ConfirmationsPage() {
  const { pending, isLoading, error } = usePendingConfirmations();
  const resolve = useResolveConfirmation();
  const [results, setResults] = useState<Record<string, ResolveResult>>({});

  return (
    <div className="mx-auto w-full max-w-3xl space-y-4 p-6">
      <header className="space-y-1">
        <h1 className="text-xl font-semibold">Pending confirmations</h1>
        <p className="text-muted-foreground text-sm">
          Actions I have stated and not taken. Nothing here has happened yet.
        </p>
      </header>

      {isLoading && <p className="text-muted-foreground text-sm">Loading…</p>}

      {/* FR-008. THREE STATES, NOT TWO. "I cannot tell what is pending" is a
          different fact from "nothing is pending", and rendering an empty list
          for both would tell the user the opposite of the truth in one case. */}
      {(error != null || pending?.readable === false) && (
        <Alert variant="destructive" data-testid="unreadable">
          <AlertTitle>I cannot tell what is pending</AlertTitle>
          <AlertDescription>
            The pending set could not be read, so this list may be missing
            actions rather than empty. {pending?.error ?? String(error ?? "")}
          </AlertDescription>
        </Alert>
      )}

      {pending?.readable && pending.actions.length === 0 && (
        <p className="text-muted-foreground text-sm" data-testid="empty">
          Nothing is waiting for you.
        </p>
      )}

      {pending?.actions.map((action) => (
        <PendingActionCard
          key={action.id}
          action={action}
          busy={resolve.isPending}
          result={results[action.id]}
          onResolve={(confirm, typedCount) =>
            resolve.mutate(
              { id: action.id, confirm, typedCount },
              {
                onSuccess: (result) =>
                  setResults((previous) => ({
                    ...previous,
                    [action.id]: result,
                  })),
              },
            )
          }
        />
      ))}
    </div>
  );
}
