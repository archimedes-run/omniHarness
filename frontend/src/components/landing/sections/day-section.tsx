import { SECTION_IDS } from "../links";

import { SectionHeading } from "./section-heading";

/** Generic sample moments; every one is something the app does today. */
const MOMENTS = [
  {
    time: "8:45 AM",
    text: "Your morning briefing lands in Telegram: today's calendar, the inbox, and what moved overnight.",
  },
  {
    time: "10:20 AM",
    text: "“Compare three standing desks under $600.” The researcher answers with sourced links, no interruptions.",
  },
  {
    time: "1:05 PM",
    text: "A specialist agent finishes a repository review, and its report opens in the file panel beside the chat.",
  },
  {
    time: "3:40 PM",
    text: "The inbox agent proposes deleting 14 newsletters, then waits for your Confirm before anything is removed.",
  },
  {
    time: "6:10 PM",
    text: "Your terminal coding agent has finished; Home shows the session is waiting on you.",
  },
];

export function DaySection() {
  const id = SECTION_IDS.day;
  return (
    <section
      id={id}
      aria-labelledby={`${id}-title`}
      className="border-border scroll-mt-20 border-t px-4 py-16 sm:px-6 sm:py-20"
    >
      <SectionHeading
        id={id}
        title="A day with OmniHarness"
        lead="It works in the background and tells you when something needs you."
      />
      <ol className="mx-auto mt-10 flex max-w-3xl flex-col gap-3">
        {MOMENTS.map((m) => (
          <li
            key={m.time}
            className="border-border bg-card flex flex-col gap-1 rounded-xl border px-4 py-3 sm:flex-row sm:items-baseline sm:gap-5"
          >
            <time className="text-muted-foreground w-20 shrink-0 text-sm tabular-nums">
              {m.time}
            </time>
            <span className="text-foreground text-sm leading-relaxed sm:text-base">
              {m.text}
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}
