"use client";

import { ArrowRightIcon, GitHubLogoIcon } from "@radix-ui/react-icons";
import Link from "next/link";
import { useEffect, useRef } from "react";

import { cn } from "@/lib/utils";

// Characters ordered light → dense. More spaces = more whitespace = lighter feel.
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
      // At font-size 9px in a typical monospace font, chars are ~5.4 px wide × 13 px tall
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

          // Multi-frequency wave interference — organic, ever-shifting
          const v =
            Math.sin(fx + t * 0.65) * Math.cos(fy + t * 0.42) * 0.48 +
            Math.sin(fx * 0.55 - fy * 0.85 + t * 1.05) * 0.3 +
            Math.cos((fx + fy) * 0.5 + t * 0.33) * 0.22;

          // Map [-1, 1] → [0, 1)
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
      className="pointer-events-none absolute inset-0 overflow-hidden whitespace-pre font-mono text-[9px] leading-[13px] tracking-[0.01em] text-stone-900/[0.07] select-none"
    />
  );
}

export function Hero({ className }: { className?: string }) {
  return (
    <section
      className={cn(
        "relative flex min-h-screen items-center justify-center overflow-hidden px-6",
        className,
      )}
    >
      {/* ASCII wave animation fills the entire viewport */}
      <AsciiBackground />

      {/* Soft radial vignette so the centre text reads cleanly */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            "radial-gradient(ellipse 55% 52% at 50% 48%, #F5F0E8 0%, rgba(245,240,232,0.82) 45%, rgba(245,240,232,0.25) 75%, transparent 100%)",
        }}
      />

      {/* ── Content ─────────────────────────────────────────────────── */}
      <div className="relative z-10 mx-auto flex max-w-3xl flex-col items-center gap-7 text-center">
        {/* Badge */}
        <div className="inline-flex items-center gap-2 rounded-full border border-stone-300/70 bg-stone-100/70 px-4 py-1.5 text-xs font-medium text-stone-500 backdrop-blur-sm">
          <span className="size-1.5 rounded-full bg-emerald-500" />
          Open source · MIT · Self-hostable in minutes
        </div>

        {/* Headline */}
        <h1 className="text-5xl font-bold leading-[1.08] tracking-tight text-stone-900 md:text-[4.5rem]">
          Research, code &amp; create
          <br />
          <span className="text-stone-400">with one super&#8209;agent.</span>
        </h1>

        {/* Description */}
        <p className="max-w-xl text-base leading-relaxed text-stone-500 md:text-lg">
          OmniHarness is an open&#8209;source AI agent harness with sandboxed
          code execution, persistent memory, composable skills, and sub&#8209;agent
          delegation — built to handle tasks that take minutes to hours.
        </p>

        {/* CTAs */}
        <div className="mt-1 flex flex-col items-center gap-3 sm:flex-row">
          <Link href="/workspace">
            <span className="inline-flex h-11 cursor-pointer items-center gap-2 rounded-lg bg-stone-900 px-7 text-sm font-semibold text-white transition-colors hover:bg-stone-700">
              Start for free
              <ArrowRightIcon className="size-4" />
            </span>
          </Link>
          <a
            href="https://github.com/archimedes-run/omni-harness"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex h-11 items-center gap-2 rounded-lg border border-stone-300 bg-transparent px-7 text-sm font-semibold text-stone-700 transition-colors hover:border-stone-400 hover:bg-stone-100/60"
          >
            <GitHubLogoIcon className="size-4" />
            View on GitHub
          </a>
        </div>

        {/* Trust line */}
        <p className="text-xs text-stone-400">
          No account required &nbsp;·&nbsp; Deploy on your own infra &nbsp;·&nbsp; Apache&nbsp;2.0
        </p>
      </div>

      {/* Bottom fade into page */}
      <div
        aria-hidden
        className="pointer-events-none absolute bottom-0 left-0 right-0 h-40"
        style={{
          background:
            "linear-gradient(to bottom, transparent, #F5F0E8)",
        }}
      />
    </section>
  );
}
