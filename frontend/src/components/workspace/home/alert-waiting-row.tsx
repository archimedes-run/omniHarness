"use client";

import { BellIcon } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { ago, ruleTitle } from "@/core/home/logic";
import type { Alert } from "@/core/inbox/types";

const STATE: Record<string, string> = {
  waiting: "Waiting to be sent",
  "not-delivered": "Not delivered",
};

/**
 * A missed or held automation alert, as a Waiting row (the Main board has no
 * separate "While you were away" block). Dismissing it is kept on the server
 * and takes it out of the New chat badge.
 */
export function AlertWaitingRow({
  alert,
  now,
  busy,
  onDismiss,
}: {
  alert: Alert;
  now: Date;
  busy: boolean;
  onDismiss: () => void;
}) {
  const when = ago(alert.at, now);
  return (
    <div
      className="border-border flex flex-wrap items-center gap-4 border-t px-5 py-3.5"
      data-testid="alert"
      data-state={alert.state}
    >
      <BellIcon
        className="text-foreground-2 size-5 shrink-0"
        aria-hidden="true"
      />
      <div className="min-w-0 flex-[1_1_360px] space-y-0.5">
        <p className="text-muted-foreground text-xs">
          Automation · {ruleTitle(alert.rule_id)} ·{" "}
          <span
            className={
              alert.state === "not-delivered"
                ? "text-destructive"
                : "text-warning"
            }
          >
            {STATE[alert.state] ?? alert.state}
          </span>
        </p>
        <p className="text-foreground text-sm" data-testid="reason">
          {alert.reason || "No reason was recorded."}
        </p>
        <p className="text-muted-foreground text-xs">
          {when ? `Recorded · ${when}` : "Recorded"}
          {alert.thread_id && (
            <>
              {" · "}
              <Link
                className="text-primary underline-offset-4 hover:underline"
                href={`/workspace/chats/${alert.thread_id}`}
              >
                Open the conversation
              </Link>
            </>
          )}
        </p>
      </div>
      <Button
        variant="outline"
        className="border-border-strong h-auto min-h-11 rounded-lg px-3.5 py-2 md:min-h-0"
        aria-label={`Dismiss ${alert.rule_id}`}
        data-testid="dismiss-alert"
        disabled={busy}
        onClick={onDismiss}
      >
        Dismiss
      </Button>
    </div>
  );
}
