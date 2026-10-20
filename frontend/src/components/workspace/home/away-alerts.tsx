"use client";

import { XIcon } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { AlertRow } from "@/components/workspace/inbox/alert-row";
import { useDismissAlerts } from "@/core/home/hooks";
import { alertKey } from "@/core/home/logic";
import { countsTowardBadge, useInboxAlerts } from "@/core/inbox/hooks";

import { CantTell, Empty, HomeCard, Loading } from "./home-card";

/**
 * While you were away: alerts the automations held or could not deliver.
 * Dismissing one is kept on the server (per user, every device) and takes it
 * out of the New chat badge. Delivered history is in the Activity log.
 */
export function AwayAlerts() {
  const { alerts, isLoading, error } = useInboxAlerts();
  const dismiss = useDismissAlerts();
  const away = alerts?.alerts.filter(countsTowardBadge);
  return (
    <HomeCard
      id="away"
      title="While you were away"
      testId="home-away"
      action={
        away && away.length > 1 ? (
          <Button
            variant="ghost"
            size="sm"
            className="max-md:min-h-11"
            disabled={dismiss.isPending}
            onClick={() => dismiss.mutate(away.map(alertKey))}
            data-testid="dismiss-all"
          >
            Dismiss all
          </Button>
        ) : undefined
      }
    >
      {isLoading && <Loading />}
      {error != null && (
        <CantTell testId="alerts-unreadable">
          {`I can't read the alert record, so this may be missing alerts rather than empty. ${String(error)}`}
        </CantTell>
      )}
      {alerts?.dismissals_readable === false && (
        <CantTell testId="dismissals-unreadable">
          Your dismissals could not be read, so alerts you dismissed may show
          again.
        </CantTell>
      )}
      {dismiss.isError && (
        <CantTell testId="dismiss-failed">
          {`That dismissal was not saved: ${dismiss.error.message}`}
        </CantTell>
      )}
      {away?.length === 0 && (
        <Empty testId="no-alerts">Nothing missed while you were away.</Empty>
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
                  disabled={dismiss.isPending}
                  onClick={() => dismiss.mutate([alertKey(a)])}
                >
                  <XIcon className="size-4" />
                </button>
              }
            />
          ))}
        </ul>
      )}
      <p className="text-muted-foreground text-xs">
        A dismissal is kept on your account, on every device. Everything
        delivered is in the{" "}
        <Link
          href="/workspace/settings/activity"
          className="text-primary underline-offset-4 hover:underline"
        >
          Activity log
        </Link>
        .
      </p>
    </HomeCard>
  );
}
