"use client";

import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

const HARNESS_LAYERS = [
  {
    id: "01",
    title: "Runtime core",
    description:
      "What thinks, reasons, and carries context from one run to the next.",
    items: ["Agent", "Model config", "Skills", "Memory"],
  },
  {
    id: "02",
    title: "Connected systems",
    description: "What the worker can reach, govern, and operate through.",
    items: ["Tools", "MCP servers", "Permissions", "Schedules"],
  },
  {
    id: "03",
    title: "Execution and outputs",
    description:
      "Where work becomes inspectable, debuggable, shareable, and reusable.",
    items: [
      "Workflows",
      "Sandboxed files",
      "Logs",
      "Artifacts",
      "Live previews",
    ],
  },
];

const STAGGER_MS = 190;

export function HarnessDefinitionSection({
  className,
}: {
  className?: string;
}) {
  const sectionRef = useRef<HTMLDivElement>(null);
  const [revealed, setRevealed] = useState<boolean[]>(
    HARNESS_LAYERS.map(() => false),
  );

  useEffect(() => {
    const el = sectionRef.current;
    if (!el) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry.isIntersecting) return;
        observer.disconnect();
        HARNESS_LAYERS.forEach((_, i) => {
          setTimeout(() => {
            setRevealed((prev) => {
              const next = [...prev];
              next[i] = true;
              return next;
            });
          }, i * STAGGER_MS);
        });
      },
      { threshold: 0.12 },
    );

    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  return (
    <section
      ref={sectionRef}
      className={cn(
        "mx-auto w-full max-w-6xl px-4 py-10 sm:px-6 sm:py-12",
        className,
      )}
    >
      <div className="rounded-[32px] border border-stone-200 bg-stone-50 p-6 sm:p-8">
        <div className="grid gap-8 lg:grid-cols-[0.88fr_1.12fr] lg:items-start">
          <div>
            <p className="text-xs font-semibold tracking-[0.18em] text-stone-400 uppercase">
              What is a harness?
            </p>
            <h2 className="mt-4 text-3xl font-bold tracking-tight text-balance text-stone-950 sm:text-4xl">
              A harness is the full operating environment behind an AI worker.
            </h2>
            <p className="mt-5 text-base leading-relaxed text-pretty text-stone-500">
              It wraps the worker itself together with its connected systems,
              runtime, permissions, and outputs so the result can be run,
              inspected, repaired, scheduled, and shared like a real product.
            </p>
          </div>

          <div className="space-y-4">
            {HARNESS_LAYERS.map((layer, index) => (
              <div
                key={layer.title}
                style={{
                  opacity: revealed[index] ? 1 : 0,
                  transform: revealed[index]
                    ? "translateY(0px)"
                    : "translateY(28px)",
                  transition:
                    "opacity 0.52s cubic-bezier(0.22,1,0.36,1), transform 0.52s cubic-bezier(0.22,1,0.36,1)",
                }}
                className={cn(
                  "rounded-[28px] border border-stone-200 bg-white p-5 shadow-[0_16px_40px_rgba(15,23,42,0.04)]",
                  index === 1 && "lg:ml-8",
                  index === 2 && "lg:ml-16",
                )}
              >
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <p className="text-xs font-semibold tracking-[0.18em] text-stone-400 uppercase">
                      Layer {layer.id}
                    </p>
                    <h3 className="mt-2 text-xl font-semibold text-stone-950">
                      {layer.title}
                    </h3>
                  </div>
                  <span className="rounded-full border border-stone-200 bg-stone-50 px-2.5 py-1 text-[10px] font-semibold text-stone-500">
                    Harness
                  </span>
                </div>

                <p className="mt-3 max-w-xl text-sm leading-relaxed text-stone-500">
                  {layer.description}
                </p>

                <div className="mt-4 grid gap-x-6 gap-y-2 sm:grid-cols-2">
                  {layer.items.map((item) => (
                    <div
                      key={item}
                      className="flex items-center gap-2 border-t border-stone-100 pt-2 text-sm font-medium text-stone-700"
                    >
                      <span className="size-1.5 rounded-full bg-stone-900" />
                      {item}
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
