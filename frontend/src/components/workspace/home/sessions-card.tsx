"use client";

import Link from "next/link";

import { BrandLogo } from "@/components/brand";
import { ageOf, sessionStatus, type Tone } from "@/core/home/logic";
import { STATE_LABEL } from "@/core/sessions/logic";
import { cn } from "@/lib/utils";

import { CantTell, Empty, HomeCard, Loading } from "./home-card";
import type { SessionsState } from "./use-home-sessions";

const SHOWN = 5;

export const TONE: Record<Tone, string> = {
  good: "text-success",
  warn: "text-warning",
  bad: "text-destructive",
  muted: "text-muted-foreground",
};

/**
 * Coding sessions (Main board): what the session watcher sees, with each
 * provider's logo and the sessions page's own status words, then the
 * watcher's health ("Watcher live · updated 12s ago", or why it can't tell).
 */
export function SessionsCard({
  sessions,
  now,
}: {
  sessions: SessionsState;
  now: Date;
}) {
  const { view, health, isLoading, cantTell } = sessions;
  const rows = cantTell == null ? (view?.sessions ?? undefined) : undefined;
  return (
    <HomeCard
      id="sessions"
      title="Coding sessions"
      testId="home-sessions"
      action={
        <Link
          href="/workspace/sessions"
          className="text-primary text-xs underline-offset-4 hover:underline"
        >
          All sessions
        </Link>
      }
    >
      {isLoading && <Loading />}
      {cantTell && (
        <CantTell testId="home-sessions-unreadable">
          {`Can't tell: ${cantTell}. Sessions may be running.`}
        </CantTell>
      )}
      {view?.agents
        ?.filter((agent) => !agent.readable)
        .map((agent) => (
          <CantTell key={agent.agent} testId="agent-unreadable">
            {`Can't read ${agent.label} sessions: ${agent.reason ?? "unknown reason"}.`}
          </CantTell>
        ))}
      {rows?.length === 0 && (
        <Empty testId="home-sessions-empty">No sessions seen.</Empty>
      )}
      {rows && rows.length > 0 && (
        <ul className="flex flex-col gap-3">
          {rows.slice(0, SHOWN).map((s) => {
            const status = sessionStatus(s, STATE_LABEL, now);
            const label = s.agent_label ?? "Coding agent";
            return (
              <li
                key={s.session_id}
                className="flex items-center gap-2.5"
                data-testid="home-session"
                data-state={s.display_state}
              >
                <BrandLogo
                  source={s.agent ?? s.agent_label}
                  name={label}
                  size={22}
                />
                <span
                  className="text-foreground min-w-0 flex-1 truncate text-sm"
                  title={s.project}
                >
                  {s.project}
                </span>
                <span
                  className={cn("shrink-0 text-xs", TONE[status.tone])}
                  data-testid="home-session-status"
                >
                  {status.text}
                </span>
              </li>
            );
          })}
        </ul>
      )}
      {rows && rows.length > SHOWN && (
        <p className="text-muted-foreground text-xs">
          {`and ${rows.length - SHOWN} more`}
        </p>
      )}
      {health && (
        <p
          className="text-muted-foreground border-border border-t pt-2.5 text-xs"
          data-testid="watcher-line"
          data-health={health.kind}
        >
          {health.kind === "live"
            ? `Watcher live · updated ${ageOf(view?.staleness_seconds) ?? "just now"}`
            : health.kind === "stale"
              ? `Watcher stale · last seen ${health.age} ago`
              : health.kind === "last-known"
                ? `Watcher did not answer · showing what it said ${health.age} ago`
                : health.kind === "never-observed"
                  ? "Watcher running · it has not seen a session yet"
                  : "Watcher: can't tell"}
        </p>
      )}
    </HomeCard>
  );
}
