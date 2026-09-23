"use client";

import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  canConfirm,
  canDecline,
  formatRemaining,
  isExpired,
  requiresTypedCount,
} from "@/core/confirmations/logic";
import type { PendingAction, ResolveResult } from "@/core/confirmations/types";

/** Colours come from theme tokens only. A literal here would be invisible in
 *  one theme, which is how the sidebar label ended up unreadable until it was
 *  hovered. */
export function PendingActionCard({
  action,
  onResolve,
  busy,
  result,
}: {
  action: PendingAction;
  onResolve: (confirm: boolean, typedCount?: number) => void;
  busy: boolean;
  result?: ResolveResult;
}) {
  const [typed, setTyped] = useState("");
  // FR-005: the clock drives expiry, not the fetch. Without this an action
  // that lapses while you are reading it still looks actionable, and pressing
  // Confirm would fail for a reason the screen never showed.
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  const expired = isExpired(action, now);
  const needsCount = requiresTypedCount(action);

  return (
    <Card
      data-testid="pending-action"
      data-action-id={action.id}
      data-expired={expired}
    >
      <CardHeader className="flex flex-row items-start justify-between gap-4">
        <div className="space-y-1">
          <p className="font-medium">{action.tool_name}</p>
          <p className="text-muted-foreground text-sm">
            {action.requester}
            {action.delegation_chain.length > 0 && (
              <span> — via {action.delegation_chain.join(" → ")}</span>
            )}
          </p>
        </div>
        <Badge
          variant={expired ? "outline" : "secondary"}
          data-testid="remaining"
        >
          {formatRemaining(action.expires_at, now)}
        </Badge>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* The plan EXACTLY as it was stated. Not a summary: confirming a
            description authorises whatever it later turns out to mean. */}
        <pre className="text-foreground bg-muted overflow-x-auto rounded-md p-3 text-sm whitespace-pre-wrap">
          {action.plan_text}
        </pre>

        <div>
          <p className="text-muted-foreground mb-1 text-xs uppercase">
            {action.targets.length} item(s) this authorises
          </p>
          <ul
            className="list-disc space-y-1 pl-5 text-sm"
            data-testid="targets"
          >
            {action.targets.map((target) => (
              <li key={target}>{target}</li>
            ))}
          </ul>
        </div>

        {needsCount && !expired && (
          <div className="space-y-1">
            <label className="text-sm" htmlFor={`count-${action.id}`}>
              This affects {action.targets.length} items, more than the{" "}
              {action.threshold_targets} I ask you to confirm by count. Type the
              number to continue.
            </label>
            <Input
              id={`count-${action.id}`}
              data-testid="typed-count"
              inputMode="numeric"
              value={typed}
              onChange={(event) => setTyped(event.target.value)}
              placeholder={String(action.targets.length)}
            />
          </div>
        )}

        {result && <ResolveMessage result={result} />}

        <div className="flex gap-2">
          <Button
            data-testid="confirm"
            disabled={busy || !canConfirm(action, typed, now)}
            onClick={() =>
              onResolve(true, needsCount ? Number(typed) : undefined)
            }
          >
            Confirm
          </Button>
          {/* FR-003: as available and as deterministic as confirming. Never
              gated by the threshold — proof of reading is required to ACT, not
              to refuse, and a harder decline pushes a hesitant user toward the
              dangerous answer. */}
          <Button
            data-testid="decline"
            variant="outline"
            disabled={busy || !canDecline(action, now)}
            onClick={() => onResolve(false)}
          >
            Decline
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

/** Every outcome says what actually happened. FR-006/FR-007: "the items
 *  changed" and "someone else confirmed it first" are not failures to retry. */
function ResolveMessage({ result }: { result: ResolveResult }) {
  const drifted = result.outcome === "targets_drifted";
  const confirmed = (result.detail?.confirmed as string[] | undefined) ?? [];
  const current = (result.detail?.current as string[] | undefined) ?? [];

  return (
    <div
      className="border-border bg-muted rounded-md border p-3 text-sm"
      data-testid="resolve-message"
      data-outcome={result.outcome}
    >
      <p>{result.message}</p>
      {drifted && (
        <div className="text-muted-foreground mt-2 space-y-1 text-xs">
          <p>You confirmed: {confirmed.join(", ") || "—"}</p>
          <p>Now present: {current.join(", ") || "—"}</p>
        </div>
      )}
    </div>
  );
}
