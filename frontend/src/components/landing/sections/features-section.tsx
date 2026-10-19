import {
  BotIcon,
  BoxesIcon,
  FolderKanbanIcon,
  LockKeyholeIcon,
  NetworkIcon,
  ScrollTextIcon,
} from "lucide-react";

import { cn } from "@/lib/utils";

export function FeaturesSection({ className }: { className?: string }) {
  const features = [
    {
      icon: BotIcon,
      kicker: "Runtime",
      title: "Agent Runtime",
      description:
        "Run long-lived agents with memory, tools, skills, sub-agents, and structured execution paths that stay inspectable as they work.",
    },
    {
      icon: NetworkIcon,
      kicker: "Integration",
      title: "MCP Tooling",
      description:
        "Connect external systems through MCP and turn them into first-class agent tools instead of brittle glue around a prompt.",
    },
    {
      icon: ScrollTextIcon,
      kicker: "Automation",
      title: "Workflow Automation",
      description:
        "Move from one-off prompts to repeatable workflows, approvals, scheduled tasks, and operational runs with durable state.",
    },
    {
      icon: BoxesIcon,
      kicker: "Execution",
      title: "Sandboxed Execution",
      description:
        "Give agents a real filesystem, shell, project workspace, and isolated runtime to build and operate actual projects safely.",
    },
    {
      icon: FolderKanbanIcon,
      kicker: "Workbench",
      title: "Project Workbench",
      description:
        "Build apps, dashboards, APIs, reports, and tools with live preview, file trees, logs, artifacts, and restartable sessions.",
    },
    {
      icon: LockKeyholeIcon,
      kicker: "Control",
      title: "Governance",
      description:
        "Keep control with self-hosting, permissions, auditability, tool boundaries, approval flows, and infrastructure you actually own.",
    },
  ];

  return (
    <section
      id="platform"
      className={cn(
        "mx-auto w-full max-w-6xl px-4 py-20 sm:px-6 sm:py-24",
        className,
      )}
    >
      <div className="mb-14 flex flex-col items-center gap-3 text-center">
        <p className="text-muted-foreground text-xs font-semibold tracking-widest uppercase">
          Built for real AI operations
        </p>
        <h2 className="text-foreground max-w-3xl text-4xl font-bold tracking-tight text-balance md:text-5xl">
          The suite you need to build, run, and govern harnesses
        </h2>
        <p className="text-muted-foreground max-w-2xl text-base leading-relaxed text-pretty">
          OmniHarness is not just a chat surface. It is an operational layer for
          agents, tools, workflows, execution, previews, and governed
          infrastructure.
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {features.map(({ icon: Icon, kicker, title, description }) => (
          <div
            key={title}
            className="group border-border bg-card hover:border-input flex h-full flex-col gap-5 rounded-3xl border p-6 transition-all duration-200 hover:-translate-y-0.5 hover:shadow-[0_16px_40px_rgba(15,23,42,0.08)]"
          >
            <div className="flex items-start justify-between gap-4">
              <div className="border-border bg-muted text-foreground flex size-11 items-center justify-center rounded-2xl border">
                <Icon className="size-5" />
              </div>
              <span className="border-border bg-muted text-muted-foreground rounded-full border px-2.5 py-1 text-[10px] font-semibold tracking-[0.18em] uppercase">
                {kicker}
              </span>
            </div>
            <div className="flex flex-1 flex-col gap-2">
              <h3 className="text-foreground text-lg font-semibold">{title}</h3>
              <p className="text-muted-foreground text-sm leading-relaxed">
                {description}
              </p>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
