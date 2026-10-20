"use client";

import { useUpcoming } from "@/core/home/hooks";
import { clock, dayLabel, sortTime, whenLabel } from "@/core/home/logic";

import { CantTell, Empty, HomeCard, Loading } from "./home-card";

const SHOWN = 6;

interface Entry {
  key: string;
  when: string;
  at: number;
  title: string;
  note: string;
  hint?: string;
  kind: "calendar" | "automation";
}

/**
 * Upcoming (Main board): the next 7 days of Google Calendar (read through the
 * existing connection) and the next run of each enabled scheduled automation
 * (computed by the gateway exactly as the engine schedules it), soonest
 * first, in the viewer's time. A run that quiet hours will hold says when its
 * message comes. The calendar is "Not set up" without a connection, and
 * "can't tell" when it could not be read.
 */
export function UpcomingCard({ now }: { now: Date }) {
  const { upcoming, error, isLoading } = useUpcoming();
  const calendar = upcoming?.calendar;
  const entries: Entry[] = [
    ...(calendar?.events ?? []).map((e, i) => ({
      key: `cal-${i}`,
      when: e.all_day ? dayLabel(e.start, now) : whenLabel(e.start, now),
      at: sortTime(e.start, e.all_day),
      title: e.title,
      note: "",
      kind: "calendar" as const,
    })),
    ...(upcoming?.runs ?? []).map((r) => ({
      key: `run-${r.rule_id}`,
      when: whenLabel(r.at, now),
      at: new Date(r.at).getTime(),
      title: r.title,
      note: r.held_until
        ? ` · automation, held to ${clock(r.held_until)} (quiet hours)`
        : " · automation",
      hint: r.prompt,
      kind: "automation" as const,
    })),
  ].sort((a, b) => a.at - b.at);
  const automationsKnown =
    upcoming != null && (!upcoming.engine_enabled || !upcoming.rules_error);
  const calendarKnown = calendar?.state !== "unavailable";

  return (
    <HomeCard id="upcoming" title="Upcoming" testId="home-upcoming">
      {isLoading && <Loading />}
      {error != null && (
        <CantTell testId="home-upcoming-unreadable">
          {`Can't tell what is coming up: ${error instanceof Error ? error.message : String(error)}.`}
        </CantTell>
      )}
      {entries.slice(0, SHOWN).map((entry) => (
        <div
          key={entry.key}
          className="flex gap-3.5 text-sm"
          data-testid={
            entry.kind === "automation"
              ? "home-upcoming-run"
              : "home-upcoming-event"
          }
        >
          <span className="text-muted-foreground w-[124px] shrink-0">
            {entry.when}
          </span>
          <span className="text-foreground min-w-0" title={entry.hint}>
            {entry.title}
            {entry.note && (
              <span className="text-muted-foreground">{entry.note}</span>
            )}
          </span>
        </div>
      ))}
      {entries.length > SHOWN && (
        <p className="text-muted-foreground text-xs">
          {`and ${entries.length - SHOWN} more`}
        </p>
      )}
      {upcoming &&
        entries.length === 0 &&
        automationsKnown &&
        calendarKnown && (
          <Empty testId="home-upcoming-empty">Nothing is coming up.</Empty>
        )}
      {upcoming?.rules_error && (
        <CantTell testId="home-upcoming-rules-error">
          {`The automation rules could not be read, so runs may be missing: ${upcoming.rules_error}`}
        </CantTell>
      )}
      {calendar?.state === "unavailable" && (
        <CantTell testId="home-upcoming-calendar-unreadable">
          {`Can't tell your calendar: ${calendar.detail ?? "it could not be read"}.`}
        </CantTell>
      )}
      {upcoming && (
        <div className="text-muted-foreground border-border mt-auto flex flex-wrap gap-x-4 gap-y-1 border-t pt-2.5 text-xs">
          <span data-testid="home-upcoming-calendar">
            {calendar?.state === "not-set-up"
              ? "Calendar · Not set up"
              : calendar?.state === "ok"
                ? "Calendar · Google Calendar, next 7 days"
                : "Calendar · can't tell"}
          </span>
          {upcoming && !upcoming.engine_enabled && (
            <span data-testid="home-upcoming-off">Automations · off</span>
          )}
        </div>
      )}
    </HomeCard>
  );
}
