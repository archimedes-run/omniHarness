"use client";

import { cn } from "@/lib/utils";

const OPERATIONAL_EVENTS = [
  {
    actor: "research-worker",
    action: "claimed a competitor-intelligence run",
    result: "sourced brief outline, notes, and citations opened",
  },
  {
    actor: "mcp/postgres",
    action: "joined cohort and billing data",
    result: "dashboard metrics refreshed inside the workbench",
  },
  {
    actor: "build-worker",
    action: "repaired a preview build and restarted the app",
    result: "logs, files, and the live session stayed attached",
  },
  {
    actor: "ops-worker",
    action: "scheduled the weekly rerun behind approval gates",
    result: "handoff is durable, inspectable, and ready to reuse",
  },
];

export function WhatIsOmniHarnessSection({
  className,
}: {
  className?: string;
}) {
  return (
    <section
      id="what-is"
      className={cn(
        "mx-auto w-full max-w-6xl px-4 py-20 sm:px-6 sm:py-24",
        className,
      )}
    >
      <div className="grid gap-6 lg:grid-cols-[1.05fr_0.95fr]">
        <div className="border-border bg-card rounded-[28px] border p-6 shadow-[0_20px_50px_rgba(15,23,42,0.05)] sm:p-8">
          <p className="text-muted-foreground text-xs font-semibold tracking-[0.18em] uppercase">
            What is OmniHarness?
          </p>
          <h2 className="text-foreground mt-4 max-w-2xl text-3xl font-bold tracking-tight text-balance sm:text-4xl">
            OmniHarness packages workers, tools, and execution into reusable
            harnesses.
          </h2>
          <p className="text-muted-foreground mt-5 max-w-2xl text-base leading-relaxed text-pretty">
            Instead of leaving the outcome in a reply, OmniHarness keeps the
            worker, connected MCP systems, memory, files, logs, approvals, and
            outputs together in a harness you can run again, inspect, repair,
            and govern.
          </p>
          <p className="text-muted-foreground mt-5 max-w-2xl text-base leading-relaxed text-pretty">
            That means you can stand up a research worker, a coding workbench, a
            dashboard generator, or an approval-based automation and still
            operate it later like a real system.
          </p>
        </div>

        <div className="border-border bg-muted overflow-hidden rounded-[28px] border p-6 shadow-[0_20px_50px_rgba(15,23,42,0.05)] sm:p-8">
          <div className="flex items-center justify-between gap-4">
            <p className="text-muted-foreground text-xs font-semibold tracking-[0.18em] uppercase">
              From request to durable run
            </p>
            <span className="border-border bg-card text-muted-foreground rounded-full border px-2.5 py-1 text-[10px] font-semibold tracking-[0.16em] uppercase">
              Operate, not just answer
            </span>
          </div>

          <div className="mt-6 flex gap-4">
            <div className="relative ml-1 w-4 shrink-0">
              <div className="bg-accent absolute top-0 bottom-0 left-1/2 w-px -translate-x-1/2" />
              <div
                className="bg-foreground absolute left-1/2 h-16 w-1.5 -translate-x-1/2 rounded-full"
                style={{
                  animation: "streamTraverse 3.2s ease-in-out infinite",
                }}
              />
            </div>
            <div className="flex-1 space-y-3">
              {OPERATIONAL_EVENTS.map((event, index) => (
                <div
                  key={event.actor}
                  className="border-border bg-card rounded-2xl border p-4"
                  style={{
                    animation: `streamFloat 7s ${index * 0.35}s ease-in-out infinite`,
                  }}
                >
                  <div className="flex items-center justify-between gap-3">
                    <p className="text-foreground text-sm font-semibold">
                      {event.actor}
                    </p>
                    <span className="border-border bg-muted text-muted-foreground rounded-full border px-2 py-0.5 text-[10px] font-medium">
                      active
                    </span>
                  </div>
                  <p className="text-foreground mt-2 text-sm leading-relaxed">
                    {event.action}
                  </p>
                  <p className="text-muted-foreground mt-1 text-xs leading-relaxed">
                    {event.result}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      <style jsx>{`
        @keyframes streamTraverse {
          0% {
            top: 0;
            opacity: 0;
          }
          15% {
            opacity: 1;
          }
          85% {
            opacity: 1;
          }
          100% {
            top: calc(100% - 4rem);
            opacity: 0;
          }
        }

        @keyframes streamFloat {
          0%,
          100% {
            transform: translateY(0px);
          }
          50% {
            transform: translateY(-3px);
          }
        }
      `}</style>
    </section>
  );
}
