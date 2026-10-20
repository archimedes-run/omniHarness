import Link from "next/link";
import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import type { Alert, AlertState } from "@/core/inbox/types";

const LABEL: Record<AlertState, string> = {
  waiting: "Waiting to be sent",
  "not-delivered": "Not delivered",
  suppressed: "Not sent, by decision",
  delivered: "Delivered",
};

const VARIANT: Record<
  AlertState,
  "default" | "secondary" | "destructive" | "outline"
> = {
  waiting: "default",
  "not-delivered": "destructive",
  suppressed: "outline",
  delivered: "secondary",
};

export function AlertRow({
  alert,
  action,
}: {
  alert: Alert;
  /** A control for this row (Home: dismiss). */
  action?: ReactNode;
}) {
  return (
    <li
      className="border-border space-y-1 rounded-md border p-3"
      data-testid="alert"
      data-state={alert.state}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-foreground font-medium">{alert.rule_id}</span>
        <span className="flex items-center gap-1">
          <Badge variant={VARIANT[alert.state]}>{LABEL[alert.state]}</Badge>
          {action}
        </span>
      </div>
      <p className="text-muted-foreground text-xs">
        {new Date(alert.at).toLocaleString()} · {alert.event_type}
      </p>
      {alert.reason && (
        <p className="text-muted-foreground text-sm" data-testid="reason">
          {alert.reason}
        </p>
      )}
      {alert.thread_id && (
        <Link
          className="text-primary text-sm underline underline-offset-2"
          href={`/workspace/chats/${alert.thread_id}`}
        >
          Open the conversation
        </Link>
      )}
    </li>
  );
}
