"use client";

import Link from "next/link";

import { useMovedToday } from "@/core/home/hooks";
import { clock } from "@/core/home/logic";

import { CantTell, Empty, HomeCard, Loading } from "./home-card";

const SHOWN = 5;

/**
 * What moved today (Main board): real events since the start of the viewer's
 * day, as recorded: Project Ledger changes (with who made them) and
 * automation messages delivered. A source that could not be read is said, so
 * a short list is never mistaken for a quiet day.
 */
export function MovedCard({ now }: { now: Date }) {
  const { moved, error, isLoading } = useMovedToday(now);
  const items = moved?.items ?? [];
  const blind =
    error != null ||
    moved?.sources.ledger === "unavailable" ||
    moved?.sources.automations === "unavailable";
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
            {item.project_id ? (
              <Link
                href={`/workspace/projects/${item.project_id}`}
                className="hover:underline"
              >
                {item.text}
              </Link>
            ) : item.thread_id ? (
              <Link
                href={`/workspace/chats/${item.thread_id}`}
                className="hover:underline"
              >
                {item.text}
              </Link>
            ) : (
              item.text
            )}
            {item.by && item.by !== "you" && (
              <span className="text-muted-foreground"> · by {item.by}</span>
            )}
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
      {moved?.sources.automations === "off" && (
        <p className="text-muted-foreground text-xs">
          Automations are off, so none delivered anything.
        </p>
      )}
    </HomeCard>
  );
}
