"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  LedgerPlanEditor,
  type LedgerChange,
} from "@/components/workspace/ledger/ledger-plan-editor";
import { WithheldNotice } from "@/components/workspace/withheld-notice";
import {
  canConfirm,
  canDecline,
  formatExpiresIn,
  isExpired,
  isSettled,
  originLabel,
  requiresTypedCount,
} from "@/core/confirmations/logic";
import type { PendingAction, ResolveResult } from "@/core/confirmations/types";
import { safeField } from "@/core/display/safe";

import { ArgumentsSummary, LongText, PlanText } from "./plan-text";

/** Colours come from theme tokens only. A literal here would be invisible in
 *  one theme, which is how the sidebar label ended up unreadable until it was
 *  hovered. */
export function PendingActionCard({
  action,
  onResolve,
  onEdit,
  busy,
  result,
  onContinue,
}: {
  action: PendingAction;
  onResolve: (confirm: boolean, typedCount?: number) => void;
  /** Present for tools whose plan can be edited before confirming. */
  onEdit?: (args: Record<string, unknown>, typedCount?: number) => void;
  busy: boolean;
  result?: ResolveResult;
  /** "Continue <agent>": the agent stopped at this call and has not carried
   *  on. Continuing is the user's own turn, never automatic (plan.md §2.0). */
  onContinue?: (agent: string, actionId: string) => void;
}) {
  const [typed, setTyped] = useState("");
  // A ledger plan (Feature 005) reads as the changes it makes, and can be
  // edited before it is confirmed.
  const ledger =
    action.tool_name === "ledger_apply" &&
    Array.isArray(action.arguments?.changes);
  const [draft, setDraft] = useState<LedgerChange[] | null>(null);
  // Once it has run, been declined or been resolved elsewhere, the actions
  // are gone: the result says what happened, and nothing is left to press.
  // A refusal that can still be fixed keeps the buttons, and an edit the
  // server could not apply keeps the editor open with its reason.
  const settled = isSettled(result);
  const continueAgent =
    result?.outcome === "executed" &&
    typeof result.detail?.continue_agent === "string"
      ? result.detail.continue_agent
      : null;
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
  const suggestedBy = originLabel(action);
  // Arguments for display, when the gateway sends them (never for a ledger
  // plan, which has its own list), and whether the only "target" is the call
  // itself (nothing more specific could be named).
  const args =
    !ledger && action.arguments_display ? action.arguments_display : null;
  const callOnly =
    action.targets.length === 1 &&
    action.targets[0]!.startsWith(`${action.tool_name}(`);

  // Who asked, and how the request reached the user (FR-033): the board's
  // "via lead_agent → researcher".
  const delegated =
    action.requester !== "lead_agent" || action.delegation_chain.length > 1;

  return (
    // Chat.dc.html: a section bordered in the warning colour, its title in
    // that colour, the clock on the right, Decline and Confirm bottom right.
    <section
      aria-label="Approval needed"
      className="border-warning bg-card flex flex-col gap-3 rounded-xl border px-4 py-3.5"
      data-testid="pending-action"
      data-action-id={action.id}
      data-expired={expired}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-warning text-[13px] font-semibold">
          Needs your approval ·{" "}
          {ledger ? "Add to your projects" : action.tool_name}
        </span>
        <span className="text-muted-foreground text-xs" data-testid="remaining">
          {formatExpiresIn(action.expires_at, now)}
        </span>
      </div>
      {delegated && (
        <p className="text-muted-foreground text-xs" data-testid="provenance">
          Asked by{" "}
          <span className="text-foreground-2 font-medium">
            {action.requester}
          </span>
          {action.delegation_chain.length > 0 && (
            <span> · via {action.delegation_chain.join(" → ")}</span>
          )}
        </p>
      )}
      <div className="flex flex-col gap-4">
        {/* FR-006: content the assistant read may suggest an action, never
            confirm it. Said plainly, and only this card's button counts. */}
        {suggestedBy && (
          <p
            className="border-border text-muted-foreground rounded-md border px-3 py-2 text-sm"
            data-testid="origin-label"
          >
            <span className="text-foreground font-medium">{suggestedBy}</span>,
            not by you. Only the Confirm button here can approve it.
            {action.delegation_chain.length > 0 && (
              <span className="mt-1 block" data-testid="origin-chain">
                via {action.delegation_chain.join(" → ")}
              </span>
            )}
          </p>
        )}
        {/* The plan EXACTLY as it was stated. Not a summary: confirming a
            description authorises whatever it later turns out to mean. */}
        {action.withheld ? (
          <WithheldNotice text={action.plan_text} />
        ) : ledger ? (
          // The stated plan IS this list of changes (rendered from the same
          // arguments the tool writes), so it is shown once, as a list.
          <p className="text-muted-foreground text-sm">
            Nothing is saved until you confirm.
          </p>
        ) : (
          <PlanText text={action.plan_text} />
        )}

        {draft && !settled ? (
          <LedgerPlanEditor changes={draft} onChange={setDraft} />
        ) : settled && typeof result?.detail?.result === "string" ? (
          // Once applied, say exactly what was saved (it may be an edit of
          // the list above), in the ledger's own words, made display-safe:
          // the tool's result keeps links real for the model, so links in it
          // are defanged here.
          <p className="text-foreground text-sm" data-testid="applied">
            {safeField(result.detail.result)}
          </p>
        ) : args && callOnly ? (
          // No specific items could be named, so the "target" is the whole
          // call: shown as its arguments, one readable row each.
          <div>
            <p className="text-muted-foreground mb-1 text-xs uppercase">
              What it will run with
            </p>
            <ArgumentsSummary args={args} />
          </div>
        ) : (
          <div className="space-y-3">
            <div>
              <p className="text-muted-foreground mb-1 text-xs uppercase">
                {action.targets.length} item(s) this authorises
              </p>
              <ul
                className="list-disc space-y-1 pl-5 text-sm"
                data-testid="targets"
              >
                {action.targets.map((target, index) => (
                  <li key={`${index}-${target}`} className="break-words">
                    <LongText text={target} />
                  </li>
                ))}
              </ul>
            </div>
            {args && (
              <div>
                <p className="text-muted-foreground mb-1 text-xs uppercase">
                  What it will run with
                </p>
                <ArgumentsSummary args={args} />
              </div>
            )}
          </div>
        )}

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
        {result?.detail?.post_queued === true && (
          <p
            className="text-muted-foreground text-xs"
            data-testid="post-waiting"
          >
            Result waiting to post: it appears in the chat when the current
            reply finishes.
          </p>
        )}
        {continueAgent && onContinue && (
          <div className="flex justify-end">
            <Button
              data-testid="continue-agent"
              variant="outline"
              onClick={() => onContinue(continueAgent, action.id)}
            >
              Continue {continueAgent}
            </Button>
          </div>
        )}

        {settled ? null : draft ? (
          <div className="flex flex-wrap justify-end gap-2">
            <Button
              data-testid="save-and-confirm"
              disabled={busy || draft.length === 0 || expired}
              onClick={() =>
                onEdit?.(
                  { ...action.arguments, changes: draft },
                  needsCount ? Number(typed) : undefined,
                )
              }
            >
              Save and confirm
            </Button>
            <Button variant="ghost" onClick={() => setDraft(null)}>
              Cancel
            </Button>
          </div>
        ) : (
          <div className="flex flex-wrap justify-end gap-2">
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
            <Button
              data-testid="confirm"
              disabled={busy || !canConfirm(action, typed, now)}
              onClick={() =>
                onResolve(true, needsCount ? Number(typed) : undefined)
              }
            >
              Confirm
            </Button>
            {ledger && onEdit && (
              <Button
                data-testid="edit"
                variant="ghost"
                disabled={busy || expired}
                onClick={() =>
                  setDraft(
                    (action.arguments?.changes as LedgerChange[]).map((c) => ({
                      ...c,
                    })),
                  )
                }
              >
                Edit
              </Button>
            )}
          </div>
        )}
      </div>
    </section>
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
