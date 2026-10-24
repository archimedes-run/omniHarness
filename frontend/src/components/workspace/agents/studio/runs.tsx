"use client";

import { useAgentRuns, type AgentRuns } from "@/core/studio";
import { OUTCOME_LABEL } from "@/core/triggers/logic";
import { cn } from "@/lib/utils";

import { useStudioCopy, type StudioCopy } from "./copy";

type C = StudioCopy["agents"];

/** "Today, 6:00 PM" / "Tomorrow, 6:00 PM" / "Fri 6:00 PM", in the reader's zone. */
export function formatWhen(iso: string, c: C, now = new Date()): string {
  const at = new Date(iso);
  const time = at.toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
  });
  const day = (d: Date) => d.toDateString();
  const tomorrow = new Date(now);
  tomorrow.setDate(now.getDate() + 1);
  if (day(at) === day(now)) return `${c.today}, ${time}`;
  if (day(at) === day(tomorrow)) return `${c.tomorrow}, ${time}`;
  const weekday = at.toLocaleDateString(undefined, {
    weekday: "short",
    ...(Math.abs(at.getTime() - now.getTime()) > 6 * 86_400_000
      ? { month: "short", day: "numeric" }
      : {}),
  });
  return `${weekday} ${time}`;
}

/** The next run across this agent's enabled schedules, or why there is none. */
export function nextRunText(
  runs: AgentRuns | undefined,
  error: unknown,
  c: C,
): string {
  if (error) return c.runsUnreadable(String((error as Error).message));
  if (!runs) return "…";
  if (runs.not_set_up_reason) return c.notSetUp;
  if (runs.rules_error) return c.rulesUnreadable;
  if (!runs.engine_enabled) return c.engineOff;
  const next = runs.schedules
    .filter((s) => s.enabled && s.next_run)
    .map((s) => ({ s, at: s.held_until ?? s.next_run! }))
    .sort((a, b) => a.at.localeCompare(b.at))[0];
  if (!next) return c.noSchedule;
  return next.s.held_until
    ? `${formatWhen(next.s.next_run!, c)} (${c.heldQuiet(formatWhen(next.s.held_until, c))})`
    : formatWhen(next.s.next_run!, c);
}

export function hasActiveSchedule(runs: AgentRuns | undefined) {
  return (
    !!runs?.engine_enabled &&
    runs.schedules.some((s) => s.enabled && s.next_run)
  );
}

export function RecentRuns({ agentId }: { agentId: string }) {
  const c = useStudioCopy().agents;
  const { runs, error } = useAgentRuns(agentId);
  return (
    <div data-testid="recent-runs">
      <div className="text-muted-foreground mb-1.5 text-xs">{c.recentRuns}</div>
      {error ? (
        <p className="text-muted-foreground border-border border-t py-2.5">
          {c.runsUnreadable(String(error.message))}
        </p>
      ) : runs?.not_set_up_reason ? (
        <p className="text-muted-foreground border-border border-t py-2.5">
          {c.notSetUpWhy}
        </p>
      ) : runs?.recent.length === 0 ? (
        <p className="text-muted-foreground border-border border-t py-2.5">
          {c.noRuns}
        </p>
      ) : (
        (runs?.recent ?? []).map((f) => (
          <div
            key={`${f.rule_id}-${f.event_id}-${f.at}`}
            className="border-border flex flex-wrap gap-3 border-t py-2.5"
            data-testid="recent-run"
          >
            <span className="text-muted-foreground w-[120px] shrink-0">
              {formatWhen(f.at, c)}
            </span>
            <span className="min-w-0 flex-1">
              <span
                className={cn(
                  f.outcome === "failed" && "text-destructive",
                  f.outcome === "delivered" && "text-success",
                )}
              >
                {OUTCOME_LABEL[f.outcome]}
              </span>
              {` · ${f.rule_id}`}
              {f.reason ? (
                <span className="text-muted-foreground">{` · ${f.reason}`}</span>
              ) : null}
            </span>
          </div>
        ))
      )}
    </div>
  );
}
