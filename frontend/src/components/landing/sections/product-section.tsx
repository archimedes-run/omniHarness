import {
  BookOpen,
  Boxes,
  CalendarClock,
  Container,
  ListChecks,
  Plug,
  TerminalSquare,
  Users,
  type LucideIcon,
} from "lucide-react";

import { SECTION_IDS } from "../links";

import { SectionHeading } from "./section-heading";

/**
 * Shipped features only: each card describes something on main today (see
 * README "What's inside" and specs/). Work in flight stays off this page.
 */
const FEATURES: { icon: LucideIcon; title: string; text: string }[] = [
  {
    icon: BookOpen,
    title: "Research with sources",
    text: "The researcher reads the web with a built-in reader, through a proxy that reaches only the public internet, and answers with the links it used.",
  },
  {
    icon: Plug,
    title: "Your accounts, connected",
    text: "Gmail, Google Calendar, Drive and GitHub connectors, each with live health and a Retry when a source fails.",
  },
  {
    icon: ListChecks,
    title: "Projects and tasks",
    text: "A shared ledger of projects, goals, tasks and notes. Agents keep it current; routine changes come with an Undo.",
  },
  {
    icon: CalendarClock,
    title: "Automations",
    text: "Schedules and events in your time zone, with quiet hours, a run history for every firing, and delivery to the web or Telegram.",
  },
  {
    icon: Users,
    title: "An agent team",
    text: "@-mention a specialist into any chat. Build your own agents in Agent Studio and teach them new skills in Skill Studio.",
  },
  {
    icon: Boxes,
    title: "MCP Suite and MCP Build",
    text: "Connect MCP servers and toolkits, or describe a tool: an agent builds and tests it in a sandbox, and you approve its first run.",
  },
  {
    icon: Container,
    title: "Sandboxed code",
    text: "Code runs in a Docker sandbox per chat, never on your host, and can reach package registries and nothing else.",
  },
  {
    icon: TerminalSquare,
    title: "Coding sessions, watched",
    text: "Follows the coding agents in your terminal: working, finished, or waiting on you, with their own todo lists.",
  },
];

export function ProductSection() {
  const id = SECTION_IDS.product;
  return (
    <section
      id={id}
      aria-labelledby={`${id}-title`}
      className="border-border scroll-mt-20 border-t px-4 py-16 sm:px-6 sm:py-20"
    >
      <SectionHeading
        id={id}
        title="What it does"
        lead="Everything here ships today, in one self-hosted workspace."
      />
      <ul className="mx-auto mt-10 grid max-w-6xl grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {FEATURES.map(({ icon: Icon, title, text }) => (
          <li
            key={title}
            className="border-border bg-card flex flex-col gap-2 rounded-xl border p-5"
          >
            <Icon aria-hidden className="text-foreground size-5" />
            <h3 className="text-foreground text-base font-semibold">{title}</h3>
            <p className="text-foreground-2 text-sm leading-relaxed">{text}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}
