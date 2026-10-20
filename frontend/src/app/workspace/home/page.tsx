"use client";

import dynamic from "next/dynamic";
import Link from "next/link";

import { Greeting } from "@/components/workspace/home/greeting";
import { MovedCard } from "@/components/workspace/home/moved-card";
import { NamePrompt } from "@/components/workspace/home/name-prompt";
import { ProjectsCard } from "@/components/workspace/home/projects-card";
import { SessionsCard } from "@/components/workspace/home/sessions-card";
import { UpcomingCard } from "@/components/workspace/home/upcoming-card";
import { useHomeSessions } from "@/components/workspace/home/use-home-sessions";
import { useNow } from "@/components/workspace/home/use-now";
import { WaitingOnYou } from "@/components/workspace/home/waiting-on-you";

// The chat bar carries the chat runtime: loaded after the dashboard paints.
const HomeChatBar = dynamic(
  () => import("@/components/workspace/home/home-chat-bar"),
  {
    ssr: false,
    loading: () => (
      <div aria-hidden="true" className="bg-card h-32 w-full rounded-2xl" />
    ),
  },
);

/**
 * Home (Feature 005 Slice 3, built to Feature 006's Main board):
 *  - a greeting, the date and how many things need you;
 *  - Waiting on you: approvals (Decline / Confirm inline) and coding sessions
 *    that look blocked on you;
 *    and automation alerts missed or held, dismissable (kept on the server;
 *    the board has no separate "While you were away" block);
 *  - Projects, Coding sessions, Upcoming and What moved today;
 *  - the chat bar, at the bottom: sending starts a new chat (the board marks
 *    Home as "New chat").
 * Every block keeps "empty" apart from "can't tell". /workspace/inbox
 * redirects here.
 */
export default function HomePage() {
  const now = useNow();
  const sessions = useHomeSessions();
  return (
    // The dashboard scrolls above the chat bar, never under it: the bar stays
    // at the bottom and covers nothing.
    <div className="flex h-full flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto" data-testid="home-scroll">
        <div className="mx-auto box-border flex w-full max-w-[1040px] flex-col gap-6 px-4 pt-9 pb-6 md:px-8">
          <Greeting sessions={sessions} now={now} />
          <NamePrompt />
          <WaitingOnYou sessions={sessions} now={now} />
          <div className="grid grid-cols-[repeat(auto-fit,minmax(min(320px,100%),1fr))] gap-5">
            <ProjectsCard />
            <SessionsCard sessions={sessions} now={now} />
            <UpcomingCard now={now} />
            <MovedCard now={now} />
          </div>
          <p className="text-muted-foreground text-xs">
            A dismissed alert stays dismissed on every device. Everything
            delivered is in the{" "}
            <Link
              href="/workspace/settings/activity"
              className="text-primary underline-offset-4 hover:underline"
            >
              Activity log
            </Link>
            .
          </p>
        </div>
      </div>
      <div
        data-testid="home-chat-dock"
        className="bg-background shrink-0 px-4 pt-2 pb-7"
      >
        <div className="mx-auto w-full max-w-[816px]">
          <HomeChatBar />
        </div>
      </div>
    </div>
  );
}
