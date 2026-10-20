"use client";

import { usePendingConfirmations } from "@/core/confirmations/hooks";
import { isExpired } from "@/core/confirmations/logic";
import { dateLine, greeting, needsYou } from "@/core/home/logic";
import { countsTowardBadge, useInboxAlerts } from "@/core/inbox/hooks";
import { usePreferences } from "@/core/preferences";

import type { SessionsState } from "./use-home-sessions";

/**
 * "Good evening, Rishabh" and "Monday, October 19 · 2 things need you".
 * The count is what Home lists as needing you: approvals still open, coding
 * sessions waiting on you, and alerts missed and not dismissed. A source that
 * cannot be read makes it "at least", or "can't tell", never a smaller number.
 */
export function Greeting({
  sessions,
  now,
}: {
  sessions: SessionsState;
  now: Date;
}) {
  const { displayName } = usePreferences();
  const { pending, error: pendingError } = usePendingConfirmations();
  const { alerts, error: alertsError } = useInboxAlerts();
  const approvals =
    pending?.readable && pendingError == null
      ? pending.actions.filter((a) => !isExpired(a, now)).length
      : null;
  const away =
    alerts && alertsError == null
      ? alerts.alerts.filter(countsTowardBadge).length
      : null;
  const waiting = sessions.waiting?.length ?? null;
  return (
    <div>
      <h1
        className="text-foreground m-0 text-[28px] leading-tight font-semibold tracking-[-0.01em]"
        data-testid="greeting"
      >
        {greeting(now, displayName)}
      </h1>
      <p className="text-muted-foreground mt-1.5" data-testid="needs-you">
        {dateLine(now)} · {needsYou([waiting, approvals, away])}
      </p>
    </div>
  );
}
