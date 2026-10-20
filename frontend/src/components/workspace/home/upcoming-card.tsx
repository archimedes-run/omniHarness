"use client";

import { useUpcoming } from "@/core/home/hooks";
import { whenLabel } from "@/core/home/logic";

import { CantTell, Empty, HomeCard, Loading } from "./home-card";

/**
 * Upcoming (Main board): the next run of each enabled scheduled automation,
 * computed by the gateway from the rule's cron in the rule's own time zone,
 * shown in the viewer's. Calendar events need a calendar source the app does
 * not have yet, so that line says "Not set up" instead of showing nothing.
 */
export function UpcomingCard({ now }: { now: Date }) {
  const { upcoming, error, isLoading } = useUpcoming();
  return (
    <HomeCard id="upcoming" title="Upcoming" testId="home-upcoming">
      {isLoading && <Loading />}
      {error != null && (
        <CantTell testId="home-upcoming-unreadable">
          {`Can't tell what is coming up: ${error instanceof Error ? error.message : String(error)}.`}
        </CantTell>
      )}
      {upcoming?.rules_error && (
        <CantTell testId="home-upcoming-rules-error">
          {`The automation rules could not be read, so runs may be missing: ${upcoming.rules_error}`}
        </CantTell>
      )}
      {upcoming && !upcoming.engine_enabled && (
        <Empty testId="home-upcoming-off">
          Automations are off, so nothing is scheduled to run.
        </Empty>
      )}
      {upcoming?.engine_enabled &&
        !upcoming.rules_error &&
        upcoming.runs.length === 0 && (
          <Empty testId="home-upcoming-empty">
            No scheduled automation is coming up.
          </Empty>
        )}
      {upcoming?.runs.map((run) => (
        <div
          key={run.rule_id}
          className="flex gap-3.5 text-sm"
          data-testid="home-upcoming-run"
        >
          <span className="text-muted-foreground w-[124px] shrink-0">
            {whenLabel(run.at, now)}
          </span>
          <span className="text-foreground min-w-0" title={run.prompt}>
            {run.title}
            <span className="text-muted-foreground"> · automation</span>
          </span>
        </div>
      ))}
      <div
        className="text-muted-foreground border-border flex gap-3.5 border-t pt-2.5 text-xs"
        data-testid="home-upcoming-calendar"
      >
        <span className="w-[124px] shrink-0">Calendar</span>
        <span>Not set up</span>
      </div>
    </HomeCard>
  );
}
