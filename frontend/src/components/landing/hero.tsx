import { ArrowRightIcon, GitHubLogoIcon } from "@radix-ui/react-icons";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { GITHUB_URL } from "./links";

const MOCK_NAV = ["Home", "Chats", "Projects", "Automations", "Agents"];

/**
 * A static drawing of the workspace (not a screenshot, not live): the
 * sidebar and one exchange with the lead agent, with the inline Undo a
 * reversible change carries. The content is generic sample data.
 */
function AppMock() {
  return (
    <figure
      aria-label="The OmniHarness workspace: a chat with the lead agent"
      className="border-border bg-card mx-auto mt-12 w-full max-w-4xl overflow-hidden rounded-xl border text-left shadow-sm"
    >
      <div className="border-border text-muted-foreground flex items-center gap-2 border-b px-4 py-2 text-xs">
        <span className="font-mono">localhost:2026</span>
        <span aria-hidden>·</span>
        <span>Chats</span>
      </div>
      <div className="grid min-h-64 grid-cols-1 sm:grid-cols-[11rem_1fr]">
        <ul className="bg-surface-raised text-muted-foreground hidden flex-col gap-0.5 p-3 text-sm sm:flex">
          {MOCK_NAV.map((item) => (
            <li
              key={item}
              className={cn(
                "rounded-md px-2 py-1.5",
                item === "Chats" && "bg-card text-foreground font-medium",
              )}
            >
              {item}
            </li>
          ))}
        </ul>
        <div className="flex flex-col gap-4 p-4 sm:p-6">
          <p className="bg-surface-raised text-foreground ml-auto w-fit max-w-[85%] rounded-xl px-3.5 py-2.5 text-sm">
            Summarise my week and tell me what&apos;s overdue in Website
            relaunch.
          </p>
          <div className="flex flex-col gap-2">
            <span className="text-muted-foreground text-xs font-medium">
              Lead agent
            </span>
            <p className="text-foreground-2 max-w-[60ch] text-sm leading-relaxed">
              You have 7 meetings this week; Tuesday is the busiest. In{" "}
              <span className="text-foreground font-medium">
                Website relaunch
              </span>
              , two tasks are overdue:{" "}
              <span className="text-foreground font-medium">
                write the pricing page copy
              </span>{" "}
              and{" "}
              <span className="text-foreground font-medium">
                review the new screenshots
              </span>
              . I moved the first one to Friday.
            </p>
            <div className="border-border bg-background flex w-fit items-center gap-3 rounded-lg border px-3 py-1.5 text-xs">
              <span className="text-foreground-2">
                Moved &ldquo;Write the pricing page copy&rdquo; to Fri
              </span>
              <span
                aria-hidden
                className="text-primary pointer-events-none cursor-default font-medium select-none"
              >
                Undo
              </span>
            </div>
          </div>
        </div>
      </div>
    </figure>
  );
}

export function Hero({ className }: { className?: string }) {
  return (
    <section
      className={cn(
        "px-4 pt-16 pb-16 text-center sm:px-6 sm:pt-24 sm:pb-20",
        className,
      )}
    >
      <div className="mx-auto flex max-w-4xl flex-col items-center">
        <span className="border-border bg-card text-foreground-2 rounded-full border px-3 py-1 text-xs">
          Self-hosted · open source
        </span>

        <h1 className="text-foreground mt-6 text-4xl leading-[1.06] font-bold tracking-tight text-balance sm:text-5xl lg:text-6xl">
          A team of AI agents
          <span className="text-muted-foreground block">
            that works for you, at home.
          </span>
        </h1>

        <p className="text-foreground-2 mt-5 max-w-2xl text-base leading-relaxed text-pretty sm:text-lg">
          Chat with a lead agent that brings in specialists, keeps your projects
          up to date, runs your automations — and checks with you before
          anything irreversible.
        </p>

        <div className="mt-8 flex flex-col items-center gap-3 sm:flex-row">
          <Button asChild size="lg">
            <Link href="/workspace">
              Get started
              <ArrowRightIcon />
            </Link>
          </Button>
          <Button asChild size="lg" variant="outline">
            <a href={GITHUB_URL} target="_blank" rel="noopener noreferrer">
              <GitHubLogoIcon />
              View on GitHub
            </a>
          </Button>
        </div>
      </div>

      <AppMock />
    </section>
  );
}
