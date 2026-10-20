"use client";

import { XIcon } from "lucide-react";
import Link from "next/link";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { PendingConfirmations } from "@/components/workspace/confirmations/pending-confirmations";
import { AlertRow } from "@/components/workspace/inbox/alert-row";
import { SessionRow } from "@/components/workspace/sessions/session-row";
import { useInboxAlerts } from "@/core/inbox/hooks";
import { useSessions } from "@/core/sessions/hooks";
import { watcherHealth } from "@/core/sessions/logic";

import { alertKey, useDismissedAlerts } from "./dismissed-alerts";

/**
 * Home, INTERIM (Feature 006 Phase 1), until Home proper is built (Feature
 * 005 Slice 3). /workspace/inbox redirects here.
 *
 *  - Waiting on you: Tier 3 approvals from any conversation or Telegram, and
 *    coding sessions waiting on you.
 *  - While you were away: alerts not yet delivered or missed, dismissable
 *    (kept in this browser: the gateway has no acknowledge route).
 *  - The delivery history (delivered, suppressed) is in Settings → Activity
 *    log.
 */
export default function HomePage() {
  const { alerts, isLoading, error } = useInboxAlerts();
  const sessions = useSessions();
  const { dismissed, dismiss } = useDismissedAlerts();
  const away = alerts?.alerts.filter(
    (a) =>
      (a.state === "waiting" || a.state === "not-delivered") &&
      !dismissed.has(alertKey(a)),
  );
  const view = sessions.view;
  const health = view ? watcherHealth(view) : null;
  const waitingSessions = view?.sessions?.filter(
    (s) => s.display_state === "waiting-on-user",
  );

  return (
    <div className="mx-auto w-full max-w-3xl space-y-8 p-6">
      <header className="space-y-1">
        <h1 className="text-xl font-semibold">Home</h1>
        <p className="text-muted-foreground text-sm">
          What is waiting on you, from every conversation, coding session and
          Telegram.
        </p>
      </header>

      <section className="space-y-5" aria-labelledby="waiting-heading">
        <h2 id="waiting-heading" className="text-base font-semibold">
          Waiting on you
        </h2>

        <div className="space-y-3">
          <h3 id="confirm-heading" className="text-sm font-semibold">
            Approvals
          </h3>
          <PendingConfirmations />
        </div>

        <div className="space-y-3" data-testid="sessions-waiting">
          <h3 className="text-sm font-semibold">Coding sessions</h3>
          {sessions.isLoading && (
            <p className="text-muted-foreground text-sm">Loading…</p>
          )}
          {(sessions.error != null ||
            view?.sessions === null ||
            health?.kind === "cannot-see") && (
            // Cannot see the sessions is not "none waiting".
            <Alert data-testid="sessions-unreadable">
              <AlertTitle>I cannot tell which sessions wait on you</AlertTitle>
              <AlertDescription>
                {health?.kind === "cannot-see"
                  ? `Because ${health.why}.`
                  : String(sessions.error ?? "The watcher sent no sessions.")}
              </AlertDescription>
            </Alert>
          )}
          {waitingSessions?.length === 0 && (
            <p
              className="text-muted-foreground text-sm"
              data-testid="no-sessions-waiting"
            >
              No coding session is waiting on you
              {health?.kind === "live"
                ? "."
                : " (as of the watcher's last report)."}
            </p>
          )}
          {waitingSessions && waitingSessions.length > 0 && (
            <ul className="space-y-2">
              {waitingSessions.map((s) => (
                <SessionRow key={s.session_id} session={s} />
              ))}
            </ul>
          )}
        </div>
      </section>

      <section className="space-y-3" aria-labelledby="away-heading">
        <div className="flex items-center justify-between gap-2">
          <h2 id="away-heading" className="text-base font-semibold">
            While you were away
          </h2>
          {away && away.length > 1 && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => dismiss(away.map(alertKey))}
              data-testid="dismiss-all"
            >
              Dismiss all
            </Button>
          )}
        </div>
        {isLoading && <p className="text-muted-foreground text-sm">Loading…</p>}
        {error != null && (
          <Alert variant="destructive" data-testid="alerts-unreadable">
            <AlertTitle>I cannot read the alert record</AlertTitle>
            <AlertDescription>
              So this may be missing alerts rather than empty. {String(error)}
            </AlertDescription>
          </Alert>
        )}
        {away?.length === 0 && (
          <p className="text-muted-foreground text-sm" data-testid="no-alerts">
            No alerts waiting and none missed.
          </p>
        )}
        {away && away.length > 0 && (
          <ul className="space-y-2" data-testid="alerts-waiting">
            {away.map((a) => (
              <AlertRow
                key={alertKey(a)}
                alert={a}
                action={
                  <button
                    type="button"
                    className="text-muted-foreground hover:bg-accent hover:text-accent-foreground flex size-11 items-center justify-center rounded-md md:size-7"
                    aria-label={`Dismiss ${a.rule_id}`}
                    data-testid="dismiss-alert"
                    onClick={() => dismiss([alertKey(a)])}
                  >
                    <XIcon className="size-4" />
                  </button>
                }
              />
            ))}
          </ul>
        )}
        <p className="text-muted-foreground text-xs">
          Dismissed alerts stay dismissed in this browser only. Everything
          delivered is in the{" "}
          <Link
            href="/workspace/settings/activity"
            className="text-primary underline-offset-4 hover:underline"
          >
            Activity log
          </Link>
          .
        </p>
      </section>
    </div>
  );
}
