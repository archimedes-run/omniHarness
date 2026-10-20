"use client";

import Link from "next/link";

import { providerLink, safeField } from "@/core/display/safe";
import { useMovedToday } from "@/core/home/hooks";
import { clock } from "@/core/home/logic";

import { CantTell, Empty, HomeCard, Loading } from "./home-card";

const SHOWN = 5;

/**
 * What moved today (Main board): real events since the start of the viewer's
 * day: Project Ledger changes (with who made them), automation messages
 * delivered, coding sessions that finished or stopped on you, and GitHub pull
 * requests merged or failing checks. Each line says how it is known
 * (observed / reported / inferred). A source that could not be read is said,
 * so a short list is never mistaken for a quiet day.
 */
export function MovedCard({ now }: { now: Date }) {
  const { moved, error, isLoading } = useMovedToday(now);
  const items = moved?.items ?? [];
  const sources = moved?.sources;
  const blind =
    error != null ||
    (sources != null &&
      Object.values(sources).some((state) => state === "unavailable"));
  return (
    <HomeCard id="moved" title="What moved today" testId="home-moved">
      {isLoading && <Loading />}
      {error != null && (
        <CantTell testId="home-moved-unreadable">
          {`Can't tell what moved today: ${error instanceof Error ? error.message : String(error)}.`}
        </CantTell>
      )}
      {items.slice(0, SHOWN).map((item, index) => (
        <div
          key={`${item.at}-${index}`}
          className="flex gap-3.5 text-sm"
          data-testid="home-moved-item"
          data-source={item.source}
        >
          <span className="text-muted-foreground w-[64px] shrink-0">
            {clock(item.at)}
          </span>
          <span className="text-foreground min-w-0">
            {providerLink(item.source, item.url) ? (
              <a
                href={providerLink(item.source, item.url)!}
                target="_blank"
                rel="noreferrer"
                className="hover:underline"
              >
                {safeField(item.text)}
              </a>
            ) : item.project_id ? (
              <Link
                href={`/workspace/projects/${item.project_id}`}
                className="hover:underline"
              >
                {safeField(item.text)}
              </Link>
            ) : item.thread_id ? (
              <Link
                href={`/workspace/chats/${item.thread_id}`}
                className="hover:underline"
              >
                {safeField(item.text)}
              </Link>
            ) : (
              safeField(item.text)
            )}
            <span className="text-muted-foreground" data-testid="known">
              {` · ${item.known}`}
              {item.by && item.by !== "you" ? ` · by ${item.by}` : ""}
            </span>
          </span>
        </div>
      ))}
      {items.length > SHOWN && (
        <p className="text-muted-foreground text-xs">
          {`and ${items.length - SHOWN} more`}
        </p>
      )}
      {moved && items.length === 0 && !blind && (
        <Empty testId="home-moved-empty">Nothing has moved yet today.</Empty>
      )}
      {moved?.sources.ledger === "unavailable" && (
        <CantTell testId="home-moved-ledger-unreadable">
          Can&apos;t read the project ledger, so project changes may be missing.
        </CantTell>
      )}
      {moved?.sources.automations === "unavailable" && (
        <CantTell testId="home-moved-automations-unreadable">
          Can&apos;t read the automation log, so deliveries may be missing.
        </CantTell>
      )}
      {sources?.sessions === "unavailable" && (
        <CantTell testId="home-moved-sessions-unreadable">
          Can&apos;t reach the session watcher, so finished sessions may be
          missing.
        </CantTell>
      )}
      {sources?.github === "unavailable" && (
        <CantTell testId="home-moved-github-unreadable">
          Can&apos;t read GitHub, so merged pull requests and failing checks may
          be missing.
        </CantTell>
      )}
      {sources && (
        <p
          className="text-muted-foreground border-border mt-auto border-t pt-2.5 text-xs"
          data-testid="home-moved-sources"
        >
          {[
            sources.automations === "off" ? "Automations · off" : null,
            sources.github === "not-set-up" ? "GitHub · Not set up" : null,
            sources.sessions === "not-set-up"
              ? "Session watcher · Not set up"
              : null,
          ]
            .filter(Boolean)
            .join(" · ") || "Ledger, automations, sessions and GitHub"}
        </p>
      )}
    </HomeCard>
  );
}
