"use client";

import Link from "next/link";
import { useState } from "react";

import { BrandLogo } from "@/components/brand";
import { Button } from "@/components/ui/button";
import { WithheldNotice } from "@/components/workspace/withheld-notice";
import {
  usePendingConfirmations,
  useResolveConfirmation,
} from "@/core/confirmations/hooks";
import type { PendingAction, ResolveResult } from "@/core/confirmations/types";
import { useDismissAlerts } from "@/core/home/hooks";
import { ago, alertKey, knownBy } from "@/core/home/logic";
import { countsTowardBadge, useInboxAlerts } from "@/core/inbox/hooks";
import type { SessionRow } from "@/core/sessions/types";

import { AlertWaitingRow } from "./alert-waiting-row";
import { ApprovalRow } from "./approval-row";
import type { SessionsState } from "./use-home-sessions";

/**
 * Waiting on you (Main board): coding sessions that look blocked on the user,
 * Tier 3 approvals with Decline / Confirm inline (from every conversation and
 * Telegram), and automation alerts missed or held, dismissable (kept on the
 * server). Each source says on its own when it cannot be read; "nothing
 * waiting" is said only for a source that was read.
 */
export function WaitingOnYou({
  sessions,
  now,
}: {
  sessions: SessionsState;
  now: Date;
}) {
  const { pending, isLoading, error } = usePendingConfirmations();
  const resolve = useResolveConfirmation();
  const [resolved, setResolved] = useState<
    Record<string, { result: ResolveResult; action: PendingAction }>
  >({});
  const actions = pending?.actions ?? [];
  // A resolved action stays, with its result, until it leaves the pending set.
  const shown = [
    ...actions,
    ...Object.values(resolved)
      .map((r) => r.action)
      .filter((a) => !actions.some((p) => p.id === a.id)),
  ];
  const approvalsUnreadable = error != null || pending?.readable === false;
  const waiting = sessions.waiting;
  const inbox = useInboxAlerts();
  const dismiss = useDismissAlerts();
  const away = inbox.alerts?.alerts.filter(countsTowardBadge);
  const rows = shown.length + (waiting?.length ?? 0) + (away?.length ?? 0);

  return (
    <section
      aria-labelledby="waiting"
      className="bg-card text-card-foreground border-border rounded-xl border py-1.5"
      data-testid="waiting-on-you"
    >
      <div className="flex items-center justify-between gap-2 px-5 pt-3 pb-2">
        <h2 id="waiting" className="text-warning m-0 text-[13px] font-semibold">
          Waiting on you
        </h2>
        {away && away.length > 1 && (
          <Button
            variant="ghost"
            size="sm"
            className="h-7 max-md:min-h-11"
            disabled={dismiss.isPending}
            onClick={() => dismiss.mutate(away.map(alertKey))}
            data-testid="dismiss-all"
          >
            Dismiss all alerts
          </Button>
        )}
      </div>

      {waiting?.map((s) => (
        <WaitingSession key={s.session_id} session={s} now={now} />
      ))}

      {shown.map((action) => (
        <ApprovalRow
          key={action.id}
          action={action}
          now={now}
          busy={resolve.isPending}
          result={resolved[action.id]?.result}
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

      {away && away.length > 0 && (
        <div className="contents" data-testid="alerts-waiting">
          {away.map((a) => (
            <AlertWaitingRow
              key={alertKey(a)}
              alert={a}
              now={now}
              busy={dismiss.isPending}
              onDismiss={() => dismiss.mutate([alertKey(a)])}
            />
          ))}
        </div>
      )}

      <div className="space-y-1 px-5 pb-3 empty:hidden">
        {isLoading && <p className="text-muted-foreground text-sm">Loading…</p>}
        {approvalsUnreadable && (
          <p className="text-warning text-sm" data-testid="unreadable">
            {`I can't tell which approvals are pending: the pending set could not be read, so this may be missing some. ${pending?.error ?? (error ? String(error) : "")}`}
          </p>
        )}
        {sessions.cantTell && (
          <p className="text-warning text-sm" data-testid="sessions-unreadable">
            {`I can't tell which coding sessions wait on you: ${sessions.cantTell}.`}
          </p>
        )}
        {rows === 0 && pending?.readable && (
          <p className="text-muted-foreground text-sm" data-testid="empty">
            No approval is waiting for you.
          </p>
        )}
        {inbox.error != null && (
          <p className="text-warning text-sm" data-testid="alerts-unreadable">
            {`I can't read the alert record, so missed alerts may not be shown. ${String(inbox.error)}`}
          </p>
        )}
        {inbox.alerts?.dismissals_readable === false && (
          <p
            className="text-warning text-sm"
            data-testid="dismissals-unreadable"
          >
            Your dismissals could not be read, so alerts you dismissed may show
            again.
          </p>
        )}
        {dismiss.isError && (
          <p className="text-warning text-sm" data-testid="dismiss-failed">
            {`That dismissal was not saved: ${dismiss.error.message}`}
          </p>
        )}
        {rows === 0 && away?.length === 0 && (
          <p className="text-muted-foreground text-sm" data-testid="no-alerts">
            No automation alert was missed.
          </p>
        )}
        {rows === 0 && waiting?.length === 0 && (
          <p
            className="text-muted-foreground text-sm"
            data-testid="no-sessions-waiting"
          >
            No coding session is waiting on you
            {sessions.live ? "." : " (as of the watcher's last report)."}
          </p>
        )}
      </div>
    </section>
  );
}

function WaitingSession({ session, now }: { session: SessionRow; now: Date }) {
  const label = session.agent_label ?? "Coding agent";
  const when = ago(session.last_activity_at, now);
  return (
    <div
      className="border-border flex flex-wrap items-center gap-4 border-t px-5 py-3.5"
      data-testid="session"
      data-state={session.display_state}
      data-epistemic={session.epistemic}
    >
      <BrandLogo
        source={session.agent ?? session.agent_label}
        name={label}
        size={28}
        className="rounded-lg"
      />
      <div className="min-w-0 flex-[1_1_360px] space-y-0.5">
        <p className="text-muted-foreground truncate text-xs">
          {label} · <span className="font-mono">{session.project}</span>
        </p>
        {session.withheld ? (
          <WithheldNotice text={session.summary} />
        ) : (
          <p className="text-foreground text-sm">
            {session.summary || "Looks like it's waiting on you."}
          </p>
        )}
        <p className="text-muted-foreground text-xs" data-testid="known-by">
          {knownBy(session.epistemic)}
          {when ? ` · ${when}` : ""}
        </p>
      </div>
      <Button
        asChild
        variant="outline"
        className="border-border-strong h-auto min-h-11 rounded-lg px-3.5 py-2 md:min-h-0"
      >
        <Link href="/workspace/sessions">Open session</Link>
      </Button>
    </div>
  );
}
