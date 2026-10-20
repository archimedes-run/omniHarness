"use client";

import { ShieldIcon } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { WithheldNotice } from "@/components/workspace/withheld-notice";
import {
  canConfirm,
  canDecline,
  formatRemaining,
  isExpired,
  originLabel,
  requiresTypedCount,
} from "@/core/confirmations/logic";
import type { PendingAction, ResolveResult } from "@/core/confirmations/types";

/**
 * One Tier 3 approval as a Home row (Main board): Decline and Confirm inline.
 *
 * The same rules as the full card (PendingActionCard), from the same logic
 * and through the same route:
 *  - the plan exactly as stated, or "Withheld";
 *  - what the confirmation authorises;
 *  - FR-006: an action the user did not ask for says what suggested it, and
 *    only this button can confirm it;
 *  - FR-009: above the threshold, the count is typed before Confirm works;
 *    Decline is never gated by it;
 *  - FR-005: expiry follows the clock (`now`), not the fetch.
 * A ledger plan is edited in its chat; Home links there.
 */
export function ApprovalRow({
  action,
  now,
  busy,
  result,
  onResolve,
}: {
  action: PendingAction;
  now: Date;
  busy: boolean;
  result?: ResolveResult;
  onResolve: (confirm: boolean, typedCount?: number) => void;
}) {
  const [typed, setTyped] = useState("");
  const expired = isExpired(action, now);
  const needsCount = requiresTypedCount(action);
  const suggestedBy = originLabel(action);
  const ledger = action.tool_name === "ledger_apply";
  const settled =
    result != null &&
    !["unrecognised", "threshold_not_met"].includes(result.outcome);

  return (
    <div
      className="border-border flex flex-wrap items-center gap-4 border-t px-5 py-3.5"
      data-testid="pending-action"
      data-action-id={action.id}
      data-expired={expired}
    >
      <ShieldIcon
        className="text-foreground-2 size-5 shrink-0"
        aria-hidden="true"
      />
      <div className="min-w-0 flex-[1_1_360px] space-y-0.5">
        <p className="text-muted-foreground text-xs">
          Approval · {ledger ? "Add to your projects" : action.tool_name}
        </p>
        {action.withheld ? (
          <WithheldNotice text={action.plan_text} />
        ) : (
          <p className="text-foreground text-sm whitespace-pre-wrap">
            {action.plan_text}
          </p>
        )}
        {action.targets.length > 0 && (
          <p className="text-muted-foreground text-xs" data-testid="targets">
            Authorises {action.targets.length} item
            {action.targets.length === 1 ? "" : "s"}:{" "}
            {action.targets.join(", ")}
          </p>
        )}
        {suggestedBy && (
          <p className="text-foreground-2 text-xs" data-testid="origin-label">
            <span className="font-medium">{suggestedBy}</span>, not by you. Only
            the Confirm button here can approve it.
          </p>
        )}
        <p className="text-muted-foreground text-xs">
          {action.thread_id ? (
            <Link
              href={`/workspace/chats/${action.thread_id}`}
              className="text-primary underline-offset-4 hover:underline"
            >
              {ledger
                ? "Asked in a chat · review or edit it there"
                : "Asked in a chat"}
            </Link>
          ) : (
            <span>
              Asked {action.requester ? `by ${action.requester}` : ""}
            </span>
          )}
          {" · "}
          <span data-testid="remaining">
            {formatRemaining(action.expires_at, now)}
          </span>
        </p>
        {needsCount && !expired && !settled && (
          <div className="flex items-center gap-2 pt-1">
            <label className="text-xs" htmlFor={`home-count-${action.id}`}>
              {`This affects ${action.targets.length} items. Type the number to confirm.`}
            </label>
            <Input
              id={`home-count-${action.id}`}
              data-testid="typed-count"
              inputMode="numeric"
              className="h-8 w-20"
              value={typed}
              onChange={(event) => setTyped(event.target.value)}
              placeholder={String(action.targets.length)}
            />
          </div>
        )}
        {result && (
          <p
            className="text-foreground text-sm"
            data-testid="resolve-message"
            data-outcome={result.outcome}
          >
            {result.message}
          </p>
        )}
      </div>
      {!settled && (
        <div className="flex gap-2">
          {/* Decline: as available as confirming, never gated by the
              threshold (FR-003). */}
          <Button
            variant="outline"
            className="border-border-strong h-auto min-h-11 rounded-lg px-3.5 py-2 md:min-h-0"
            data-testid="decline"
            disabled={busy || !canDecline(action, now)}
            onClick={() => onResolve(false)}
          >
            Decline
          </Button>
          <Button
            className="h-auto min-h-11 rounded-lg px-3.5 py-2 font-semibold md:min-h-0"
            data-testid="confirm"
            disabled={busy || !canConfirm(action, typed, now)}
            onClick={() =>
              onResolve(true, needsCount ? Number(typed) : undefined)
            }
          >
            Confirm
          </Button>
        </div>
      )}
    </div>
  );
}
