"use client";

import { CircleDashedIcon, CircleDotIcon, ZapIcon } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { useSetRuleEnabled } from "@/core/automations/hooks";
import { describeSchedule, matchText } from "@/core/automations/schedule";
import {
  ACTIVITY_LABEL,
  OUTCOME_LABEL,
  timestamp,
} from "@/core/triggers/logic";
import type { Activity, RuleView } from "@/core/triggers/types";

export function summarise(rule: RuleView): string {
  if (rule.type === "cron") {
    return describeSchedule(
      matchText(rule.match.schedule),
      matchText(rule.match.timezone) || undefined,
    );
  }
  if (rule.type === "watcher") return `When: ${matchText(rule.match.event)}`;
  return rule.type;
}

/** A distinct icon per condition, so the three read apart at a glance
 * (Feature 004 FR-017, kept from the triggers page this replaced). */
const ACTIVITY_ICON: Record<Activity, typeof ZapIcon> = {
  "never-evaluated": CircleDashedIcon,
  "evaluated-never-fired": CircleDotIcon,
  fired: ZapIcon,
};

export function AutomationRow({
  rule,
  version,
  writable,
}: {
  rule: RuleView;
  version: string | null;
  writable: boolean;
}) {
  const toggle = useSetRuleEnabled();
  const Icon = ACTIVITY_ICON[rule.activity];
  return (
    <li
      className="border-border flex flex-col gap-2 rounded-md border p-3"
      data-testid="rule"
      data-rule={rule.id}
      data-activity={rule.activity}
      data-enabled={rule.enabled}
    >
      <div className="flex items-center justify-between gap-4">
        <div className="min-w-0 space-y-0.5">
          <Link
            href={`/workspace/automations/${encodeURIComponent(rule.id)}`}
            className="text-foreground font-medium hover:underline"
          >
            {rule.id}
          </Link>
          <p className="text-muted-foreground text-sm">{summarise(rule)}</p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Icon
            className="text-muted-foreground size-4"
            aria-label={rule.activity}
            data-testid="activity-icon"
          />
          <Badge variant={rule.enabled ? "secondary" : "outline"}>
            {rule.enabled ? ACTIVITY_LABEL[rule.activity] : "Off"}
          </Badge>
          <Switch
            checked={rule.enabled}
            disabled={!writable || !version || toggle.isPending}
            aria-label={`${rule.enabled ? "Turn off" : "Turn on"} ${rule.id}`}
            onCheckedChange={(enabled) =>
              version && toggle.mutate({ id: rule.id, enabled, version })
            }
          />
        </div>
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
      {toggle.error != null && (
        <p className="text-destructive text-xs" data-testid="toggle-error">
          {toggle.error.message} The rules in force have not changed.
        </p>
      )}
    </li>
  );
}
