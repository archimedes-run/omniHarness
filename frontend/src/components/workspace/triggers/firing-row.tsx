import {
  CircleAlertIcon,
  CircleCheckIcon,
  ClockIcon,
  MoonIcon,
  TimerOffIcon,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { OUTCOME_LABEL } from "@/core/triggers/logic";
import type { FiringView, Outcome } from "@/core/triggers/types";

const OUTCOME_ICON: Record<Outcome, typeof ClockIcon> = {
  delivered: CircleCheckIcon,
  suppressed: MoonIcon,
  queued: ClockIcon,
  expired: TimerOffIcon,
  failed: CircleAlertIcon,
};

export function FiringRow({ firing }: { firing: FiringView }) {
  const Icon = OUTCOME_ICON[firing.outcome];
  return (
    <li
      className="border-border flex flex-col gap-1 rounded-md border p-3"
      data-testid="firing"
      data-rule={firing.rule_id}
      data-outcome={firing.outcome}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-foreground font-medium">{firing.rule_id}</span>
        <span className="flex items-center gap-1">
          <Icon
            className="text-muted-foreground size-4"
            aria-label={firing.outcome}
            data-testid="outcome-icon"
          />
          <Badge
            variant={firing.outcome === "failed" ? "destructive" : "secondary"}
          >
            {OUTCOME_LABEL[firing.outcome]}
          </Badge>
        </span>
      </div>
      <p className="text-muted-foreground text-xs">
        {new Date(firing.at).toLocaleString()} · {firing.event_type} ·{" "}
        {firing.event_id}
      </p>
      {/* FR-019: the reason as recorded, never a status word. */}
      {firing.reason && (
        <p className="text-foreground text-sm" data-testid="reason">
          {firing.reason}
        </p>
      )}
      {/* FR-021, T058: what it was merged with, visible here. */}
      {firing.batch === "batched" && (
        <p
          className="text-muted-foreground text-xs"
          data-testid="delivered-with"
        >
          Delivered in one message with:{" "}
          {firing.delivered_with.map((m) => m.rule_id).join(", ")}
        </p>
      )}
      {firing.batch === "not-recorded" && firing.outcome === "delivered" && (
        <p
          className="text-muted-foreground text-xs"
          data-testid="batch-not-recorded"
        >
          Whether it was delivered with others: not recorded.
        </p>
      )}
    </li>
  );
}
