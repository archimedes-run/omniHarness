"use client";

import { ArrowRightIcon, GitHubLogoIcon } from "@radix-ui/react-icons";
import Link from "next/link";
import { useEffect, useRef } from "react";

import { cn } from "@/lib/utils";

const CHARS = "      ..··:::;;;+++===***???%%%##@";

function AsciiBackground() {
  const preRef = useRef<HTMLPreElement>(null);
  const rafRef = useRef<number>(0);
  const startRef = useRef(0);
  const colsRef = useRef(0);
  const rowsRef = useRef(0);

  useEffect(() => {
    startRef.current = performance.now();

    function measure() {
      const el = preRef.current;
      if (!el) return;
      const { width, height } = el.getBoundingClientRect();
      colsRef.current = Math.max(1, Math.floor(width / 5.5));
      rowsRef.current = Math.max(1, Math.floor(height / 13));
    }

    measure();
    const ro = new ResizeObserver(measure);
    if (preRef.current) ro.observe(preRef.current);

    function tick() {
      const el = preRef.current;
      if (!el) {
        rafRef.current = requestAnimationFrame(tick);
        return;
      }

      const t = (performance.now() - startRef.current) * 0.001;
      const cols = colsRef.current;
      const rows = rowsRef.current;
      const lines: string[] = [];

      for (let y = 0; y < rows; y++) {
        let line = "";
        for (let x = 0; x < cols; x++) {
          const fx = (x / cols) * Math.PI * 9;
          const fy = (y / rows) * Math.PI * 7;

          const v =
            Math.sin(fx + t * 0.65) * Math.cos(fy + t * 0.42) * 0.48 +
            Math.sin(fx * 0.55 - fy * 0.85 + t * 1.05) * 0.3 +
            Math.cos((fx + fy) * 0.5 + t * 0.33) * 0.22;

          const norm = Math.max(0, Math.min(0.999, (v + 1) * 0.5));
          line += CHARS[Math.floor(norm * CHARS.length)];
        }
        lines.push(line);
      }

      el.textContent = lines.join("\n");
      rafRef.current = requestAnimationFrame(tick);
    }

    rafRef.current = requestAnimationFrame(tick);

    return () => {
      cancelAnimationFrame(rafRef.current);
      ro.disconnect();
    };
  }, []);

  return (
    <pre
      ref={preRef}
      aria-hidden
      className="pointer-events-none absolute inset-0 overflow-hidden font-mono text-[9px] leading-[13px] tracking-[0.01em] whitespace-pre text-stone-900/[0.045] select-none"
    />
  );
}

export function Hero({ className }: { className?: string }) {
  return (
    <section
      className={cn(
        "relative flex min-h-[100svh] items-center justify-center overflow-hidden px-4 pt-28 pb-18 sm:px-6 sm:pt-32 sm:pb-24",
        className,
      )}
    >
      <AsciiBackground />

      <div
        aria-hidden
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            "radial-gradient(ellipse 56% 54% at 50% 42%, rgba(255,255,255,0.98) 0%, rgba(255,255,255,0.88) 42%, rgba(255,255,255,0.46) 72%, transparent 100%)",
        }}
      />

      <div className="relative z-10 mx-auto flex max-w-6xl flex-col items-center gap-8 text-center">
        <div className="inline-flex items-center gap-2 rounded-full border border-stone-200 bg-white/90 px-4 py-1.5 text-xs font-medium text-stone-500 shadow-sm backdrop-blur-sm">
          <span className="size-1.5 rounded-full bg-stone-900" />
          Autonomous AI workers on your infrastructure
        </div>

        <h1 className="max-w-5xl text-4xl leading-[1.04] font-bold tracking-tight text-balance text-stone-950 sm:text-5xl lg:text-[4.6rem]">
          Build autonomous AI workers that run, inspect, and repair real
          workflows.
        </h1>

        <p className="max-w-3xl text-base leading-relaxed text-pretty text-stone-600 sm:text-lg">
          OmniHarness packages agents, MCP tools, memory, workflows, and
          sandboxed execution into durable harnesses you can run, inspect,
          reuse, and govern.
        </p>

        <p className="max-w-3xl text-sm leading-relaxed text-pretty text-stone-500 sm:text-base">
          Ship research workers, coding workbenches, approval-driven
          automations, dashboard generators, and live project previews from one
          self-hosted workspace.
        </p>

        <div className="mt-1 flex flex-col items-center gap-3 sm:flex-row">
          <Link href="/workspace">
            <span className="inline-flex h-11 cursor-pointer items-center gap-2 rounded-lg bg-stone-950 px-7 text-sm font-semibold text-white transition-colors hover:bg-stone-800">
              Start building
              <ArrowRightIcon className="size-4" />
            </span>
          </Link>
          <a
            href="https://github.com/archimedes-run/omniHarness"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex h-11 items-center gap-2 rounded-lg border border-stone-300 bg-white/90 px-7 text-sm font-semibold text-stone-700 transition-colors hover:border-stone-400 hover:bg-stone-50"
          >
            <GitHubLogoIcon className="size-4" />
            View on GitHub
          </a>
        </div>

        <p className="text-xs font-medium tracking-[0.18em] text-stone-400 uppercase">
          Open source · Self-hosted · Sandbox-native · MCP-ready
        </p>
      </div>

      <div
        aria-hidden
        className="pointer-events-none absolute right-0 bottom-0 left-0 h-40"
        style={{
          background: "linear-gradient(to bottom, transparent, white)",
        }}
      />
    </section>
  );
}
