import { CircleDashedIcon, CircleDotIcon, ZapIcon } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  ACTIVITY_LABEL,
  OUTCOME_LABEL,
  timestamp,
} from "@/core/triggers/logic";
import type { Activity, RuleView } from "@/core/triggers/types";

/** A distinct icon per condition, so the three read apart at a glance (FR-017). */
const ACTIVITY_ICON: Record<Activity, typeof ZapIcon> = {
  "never-evaluated": CircleDashedIcon,
  "evaluated-never-fired": CircleDotIcon,
  fired: ZapIcon,
};

export function RuleRow({ rule }: { rule: RuleView }) {
  const Icon = ACTIVITY_ICON[rule.activity];
  return (
    <li
      className="border-border flex flex-col gap-1 rounded-md border p-3"
      data-testid="rule"
      data-rule={rule.id}
      data-activity={rule.activity}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-foreground font-medium">
          {rule.id}{" "}
          <span className="text-muted-foreground text-xs">({rule.type})</span>
        </span>
        <span className="flex items-center gap-1">
          <Icon
            className="text-muted-foreground size-4"
            aria-label={rule.activity}
            data-testid="activity-icon"
          />
          <Badge variant={rule.enabled ? "secondary" : "outline"}>
            {rule.enabled ? ACTIVITY_LABEL[rule.activity] : "Disabled"}
          </Badge>
        </span>
      </div>
      <dl className="text-muted-foreground grid grid-cols-2 gap-x-4 text-xs">
        <dt>Last evaluated</dt>
        <dd data-testid="last-evaluated">
          {timestamp(rule.last_evaluated_at, rule.last_evaluated)}
        </dd>
        <dt>Last fired</dt>
        <dd data-testid="last-fired">
          {rule.last_fired_at
            ? `${timestamp(rule.last_fired_at, "recorded")}${rule.last_outcome ? ` · ${OUTCOME_LABEL[rule.last_outcome]}` : ""}`
            : "never"}
        </dd>
      </dl>
    </li>
  );
}
