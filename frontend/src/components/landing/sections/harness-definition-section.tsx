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

// Scroll distance (px) each layer occupies.
const SEGMENT_PX = 500;
const TOTAL_SCROLL = SEGMENT_PX * HARNESS_LAYERS.length;

export function HarnessDefinitionSection({
  className,
}: {
  className?: string;
}) {
  const sectionRef = useRef<HTMLDivElement>(null);
  const rafRef = useRef<number>(0);
  const prevIndex = useRef(0);
  const [activeIndex, setActiveIndex] = useState(0);

  useEffect(() => {
    const el = sectionRef.current;
    if (!el) return;

    function tick() {
      const scrolled = -el!.getBoundingClientRect().top;
      const clamped = Math.max(0, scrolled);
      const next = Math.min(
        HARNESS_LAYERS.length - 1,
        Math.floor(clamped / SEGMENT_PX),
      );
      if (next !== prevIndex.current) {
        prevIndex.current = next;
        setActiveIndex(next);
      }
      rafRef.current = requestAnimationFrame(tick);
    }

    rafRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafRef.current);
  }, []);

  return (
    <section
      ref={sectionRef}
      className={cn("relative", className)}
      style={{ height: `calc(100vh + ${TOTAL_SCROLL}px)` }}
    >
      <div className="sticky top-0 flex h-screen items-center">
        <div className="mx-auto w-full max-w-6xl px-4 sm:px-6">
          <div className="grid items-center gap-14 lg:grid-cols-[0.9fr_1.1fr]">
            {/* ── Left: static description + progress indicators ─── */}
            <div>
              <p className="text-xs font-semibold tracking-[0.18em] text-stone-400 uppercase">
                What is a harness?
              </p>
              <h2 className="mt-4 text-3xl font-bold tracking-tight text-balance text-stone-950 sm:text-4xl">
                A harness is the full operating environment behind an AI worker.
              </h2>
              <p className="mt-5 text-base leading-relaxed text-pretty text-stone-500">
                It wraps the worker together with its connected systems,
                runtime, permissions, and outputs so the result can be run,
                inspected, repaired, scheduled, and shared like a real product.
              </p>

              {/* Step indicators */}
              <div className="mt-10 flex flex-col gap-3">
                {HARNESS_LAYERS.map((layer, i) => (
                  <div key={layer.id} className="flex items-center gap-3">
                    <div
                      className={cn(
                        "h-[2px] shrink-0 rounded-full transition-all duration-500 ease-out",
                        i === activeIndex
                          ? "w-8 bg-stone-900"
                          : i < activeIndex
                            ? "w-4 bg-stone-400"
                            : "w-4 bg-stone-200",
                      )}
                    />
                    <span
                      className={cn(
                        "text-xs font-medium transition-colors duration-300",
                        i === activeIndex
                          ? "text-stone-900"
                          : i < activeIndex
                            ? "text-stone-400"
                            : "text-stone-300",
                      )}
                    >
                      {layer.title}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            {/* ── Right: one card at a time ─────────────────────── */}
            <div className="relative h-[360px]">
              {HARNESS_LAYERS.map((layer, index) => (
                <div
                  key={layer.id}
                  aria-hidden={activeIndex !== index}
                  className="absolute inset-0"
                  style={{
                    opacity: activeIndex === index ? 1 : 0,
                    transform:
                      activeIndex === index
                        ? "translateY(0px) scale(1)"
                        : activeIndex > index
                          ? "translateY(-20px) scale(0.96)"
                          : "translateY(24px) scale(0.96)",
                    transition:
                      "opacity 0.42s cubic-bezier(0.22,1,0.36,1), transform 0.42s cubic-bezier(0.22,1,0.36,1)",
                    pointerEvents: activeIndex === index ? "auto" : "none",
                  }}
                >
                  <div className="flex h-full flex-col overflow-hidden rounded-[28px] border border-stone-200 bg-white shadow-[0_24px_80px_rgba(15,23,42,0.08)]">
                    {/* Accent line */}
                    <div className="h-[3px] shrink-0 bg-gradient-to-r from-stone-900 via-stone-500 to-stone-200" />

                    <div className="relative flex flex-1 flex-col p-7">
                      {/* Watermark */}
                      <span
                        aria-hidden
                        className="pointer-events-none absolute right-5 bottom-2 leading-none font-black text-stone-100 select-none"
                        style={{ fontSize: "6.5rem" }}
                      >
                        {layer.id}
                      </span>

                      {/* Header row */}
                      <div className="flex items-center justify-between">
                        <span className="text-[10px] font-semibold tracking-[0.2em] text-stone-400 uppercase">
                          Layer {layer.id}
                        </span>
                        <span className="text-[10px] font-medium text-stone-300 tabular-nums">
                          {index + 1}&thinsp;/&thinsp;{HARNESS_LAYERS.length}
                        </span>
                      </div>

                      {/* Title */}
                      <h3 className="mt-4 text-2xl font-bold tracking-tight text-stone-950 sm:text-[1.75rem]">
                        {layer.title}
                      </h3>

                      {/* Description */}
                      <p className="mt-2.5 max-w-sm text-sm leading-relaxed text-stone-500">
                        {layer.description}
                      </p>

                      {/* Items as chips */}
                      <div className="mt-auto flex flex-wrap gap-2 pt-6">
                        {layer.items.map((item) => (
                          <span
                            key={item}
                            className="inline-flex items-center gap-1.5 rounded-full border border-stone-200 bg-stone-50 px-3 py-1 text-xs font-medium text-stone-700"
                          >
                            <span className="size-1 rounded-full bg-stone-400" />
                            {item}
                          </span>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
