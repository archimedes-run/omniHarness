"use client";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { PendingConfirmations } from "@/components/workspace/confirmations/pending-confirmations";
import { AlertRow } from "@/components/workspace/inbox/alert-row";
import { useInboxAlerts } from "@/core/inbox/hooks";

/**
 * Everything waiting on you that did not happen in the chat you are looking
 * at: Tier 3 actions from other threads or Telegram, and what the assistant
 * tried to tell you (Phase 2.5).
 */
export default function InboxPage() {
  const { alerts, isLoading, error } = useInboxAlerts();
  const waiting = alerts?.alerts.filter(
    (a) => a.state === "waiting" || a.state === "not-delivered",
  );
  const recent = alerts?.alerts.filter(
    (a) => a.state === "delivered" || a.state === "suppressed",
  );

  return (
    <div className="mx-auto w-full max-w-3xl space-y-8 p-6">
      <header className="space-y-1">
        <h1 className="text-xl font-semibold">Inbox</h1>
        <p className="text-muted-foreground text-sm">
          What is waiting on you, from every conversation and from Telegram.
        </p>
      </header>

      <section className="space-y-3" aria-labelledby="confirm-heading">
        <h2 id="confirm-heading" className="text-sm font-semibold">
          Waiting for your confirmation
        </h2>
        <PendingConfirmations />
      </section>

      <section className="space-y-3" aria-labelledby="alerts-heading">
        <h2 id="alerts-heading" className="text-sm font-semibold">
          Alerts
        </h2>
        {isLoading && <p className="text-muted-foreground text-sm">Loading…</p>}
        {error != null && (
          <Alert variant="destructive" data-testid="alerts-unreadable">
            <AlertTitle>I cannot read the alert record</AlertTitle>
            <AlertDescription>
              So this may be missing alerts rather than empty. {String(error)}
            </AlertDescription>
          </Alert>
        )}
        {alerts?.alerts.length === 0 && (
          <p className="text-muted-foreground text-sm" data-testid="no-alerts">
            No alerts in the last 24 hours, and none waiting.
          </p>
        )}
        {waiting && waiting.length > 0 && (
          <ul className="space-y-2" data-testid="alerts-waiting">
            {waiting.map((a) => (
              <AlertRow key={`${a.rule_id}-${a.event_id}`} alert={a} />
            ))}
          </ul>
        )}
        {recent && recent.length > 0 && (
          <>
            <h3 className="text-muted-foreground text-xs uppercase">
              Last 24 hours
            </h3>
            <ul className="space-y-2" data-testid="alerts-recent">
              {recent.map((a) => (
                <AlertRow key={`${a.rule_id}-${a.event_id}`} alert={a} />
              ))}
            </ul>
          </>
        )}
      </section>
    </div>
  );
}
