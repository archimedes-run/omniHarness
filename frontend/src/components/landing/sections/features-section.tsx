import { cn } from "@/lib/utils";

const features = [
  {
    icon: "⚡",
    title: "Multi-Agent Orchestration",
    description:
      "A lead agent spawns specialised sub-agents, delegates tasks, collects results, and synthesises a final answer — all in one run.",
  },
  {
    icon: "🔒",
    title: "Sandboxed Code Execution",
    description:
      "Python and shell commands run inside an isolated sandbox. No escapes, no surprises — full output streamed back in real time.",
  },
  {
    icon: "🧠",
    title: "Persistent Memory",
    description:
      "Agents remember across sessions. Facts, preferences, and context survive so every conversation picks up exactly where the last ended.",
  },
  {
    icon: "🔧",
    title: "Composable Skills",
    description:
      "Install and version skills like packages. Each skill is a typed tool with schema — mix built-ins with community or custom tools.",
  },
  {
    icon: "🌐",
    title: "Web Search & Fetch",
    description:
      "First-class live web access via Serper search and Jina AI fetch. Agents browse the web, not a stale training snapshot.",
  },
  {
    icon: "🗂️",
    title: "Artifact Management",
    description:
      "Files, code, reports, and images surface as typed artifacts. Browse, preview, and download them from a dedicated side panel.",
  },
];

export function FeaturesSection({ className }: { className?: string }) {
  return (
    <section
      className={cn(
        "mx-auto w-full max-w-5xl px-6 py-28",
        className,
      )}
    >
      {/* Section header */}
      <div className="mb-14 flex flex-col items-center gap-3 text-center">
        <p className="text-xs font-semibold uppercase tracking-widest text-stone-400">
          Built-in primitives
        </p>
        <h2 className="max-w-xl text-4xl font-bold tracking-tight text-stone-900 md:text-5xl">
          Everything a serious agent needs
        </h2>
        <p className="max-w-lg text-base leading-relaxed text-stone-500">
          Not bolted on — designed as first-class infrastructure from day one.
        </p>
      </div>

      {/* Cards */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {features.map((f) => (
          <div
            key={f.title}
            className="group flex flex-col gap-3 rounded-2xl border border-stone-200 bg-white/70 p-6 transition-shadow hover:shadow-md hover:shadow-stone-200/60"
          >
            <span className="text-2xl">{f.icon}</span>
            <h3 className="text-sm font-semibold text-stone-900">{f.title}</h3>
            <p className="text-sm leading-relaxed text-stone-500">
              {f.description}
            </p>
          </div>
        ))}
      </div>
    </section>
  );
}
