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
import { ago, knownBy } from "@/core/home/logic";
import type { SessionRow } from "@/core/sessions/types";

import { ApprovalRow } from "./approval-row";
import type { SessionsState } from "./use-home-sessions";

/**
 * Waiting on you (Main board): coding sessions that look blocked on the user,
 * and Tier 3 approvals with Decline / Confirm inline, from every conversation
 * and Telegram. Each half says on its own when it cannot be read; "nothing
 * waiting" is said only for a half that was read.
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
  const rows = shown.length + (waiting?.length ?? 0);

  return (
    <section
      aria-labelledby="waiting"
      className="bg-card text-card-foreground border-border rounded-xl border py-1.5"
      data-testid="waiting-on-you"
    >
      <h2
        id="waiting"
        className="text-warning m-0 px-5 pt-3 pb-2 text-[13px] font-semibold"
      >
        Waiting on you
      </h2>

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
