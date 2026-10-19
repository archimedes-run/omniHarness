import { cn } from "@/lib/utils";

const HARNESS_EXAMPLES = [
  {
    title: "Research Harness",
    description:
      "Search, synthesize, cite, and produce structured reports with durable source trails and artifacts.",
  },
  {
    title: "Coding Harness",
    description:
      "Generate apps and tools with live preview, logs, file tree visibility, and repair loops.",
  },
  {
    title: "MCP Harness",
    description:
      "Connect APIs and services through MCP and expose them as first-class agent-operable tools.",
  },
  {
    title: "Workflow Harness",
    description:
      "Turn recurring business processes into automated, inspectable, approval-aware runs.",
  },
  {
    title: "Data Harness",
    description:
      "Analyze files, query datasets, generate dashboards, and export operational artifacts.",
  },
  {
    title: "Operations Harness",
    description:
      "Create assistants that can monitor systems, act, notify, escalate, and stay grounded in your infra.",
  },
];

export function ExampleHarnessesSection({ className }: { className?: string }) {
  return (
    <section
      className={cn(
        "mx-auto w-full max-w-6xl px-4 py-20 sm:px-6 sm:py-24",
        className,
      )}
    >
      <div className="mb-12 flex flex-col items-center gap-3 text-center">
        <p className="text-muted-foreground text-xs font-semibold tracking-[0.18em] uppercase">
          Example harnesses
        </p>
        <h2 className="text-foreground max-w-3xl text-4xl font-bold tracking-tight text-balance md:text-5xl">
          Start with a chat. End with a runnable AI capability.
        </h2>
        <p className="text-muted-foreground max-w-2xl text-base leading-relaxed text-pretty">
          Most AI products give you a chat box. OmniHarness gives you an
          operating layer you can build on, preview, automate, and control.
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {HARNESS_EXAMPLES.map((example, index) => (
          <div
            key={example.title}
            className="border-border bg-card rounded-3xl border p-6 shadow-[0_14px_36px_rgba(15,23,42,0.04)]"
          >
            <span className="border-border bg-muted text-muted-foreground inline-flex rounded-full border px-2.5 py-1 text-[10px] font-semibold tracking-[0.16em] uppercase">
              Harness {index + 1}
            </span>
            <h3 className="text-foreground mt-4 text-xl font-semibold">
              {example.title}
            </h3>
            <p className="text-muted-foreground mt-3 text-sm leading-relaxed">
              {example.description}
            </p>
          </div>
        ))}
      </div>
    </section>
  );
}
