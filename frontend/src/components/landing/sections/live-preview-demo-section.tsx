"use client";

import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

// ── Data ──────────────────────────────────────────────────────────────────────

const STEPS = [
  {
    type: "skill" as const,
    label: "Consult web-app-builder skill",
    path: "/mnt/skills/public/web-app-builder/SKILL.md",
  },
  {
    type: "edit" as const,
    label: "Scaffold Next.js project structure",
    path: "/mnt/user-data/workspace/dashboard/package.json",
  },
  {
    type: "edit" as const,
    label: "Build LineChart component",
    path: "/mnt/user-data/workspace/dashboard/components/LineChart.tsx",
  },
  {
    type: "edit" as const,
    label: "Wire up data pipeline",
    path: "/mnt/user-data/workspace/dashboard/lib/data.ts",
  },
  {
    type: "skill" as const,
    label: "Review and verify output",
    path: "/mnt/user-data/workspace/dashboard/app/page.tsx",
  },
];

type CodeLine = { text: string; color: string };
const CODE_LINES: CodeLine[] = [
  { text: '"use client";', color: "#fb923c" },
  { text: 'import React from "react";', color: "#60a5fa" },
  { text: "", color: "" },
  { text: "type Series = {", color: "#4ade80" },
  { text: "  id      string;", color: "#d6d3d1" },
  { text: "  color   string;", color: "#d6d3d1" },
  { text: "  data    { x: Date; y: number }[];", color: "#d6d3d1" },
  { text: "};", color: "#4ade80" },
  { text: "", color: "" },
  { text: "export function LineChart({", color: "#fde047" },
  { text: "  series,", color: "#d6d3d1" },
  { text: "  width   = 800,", color: "#d6d3d1" },
  { text: "  height  = 300,", color: "#d6d3d1" },
  { text: "  yLabel,", color: "#d6d3d1" },
  { text: "}: {", color: "#fde047" },
  { text: "  series: Series[];", color: "#a8a29e" },
  { text: "  width:  number;", color: "#a8a29e" },
  { text: "  height: number;", color: "#a8a29e" },
  { text: "  yLabel: string;", color: "#a8a29e" },
  { text: "}) {", color: "#fde047" },
  {
    text: "  const pad = { top:20, right:30, bottom:40, left:60 };",
    color: "#d6d3d1",
  },
  {
    text: "  const allX = series.flatMap(s => s.data.map(d => d.x));",
    color: "#d6d3d1",
  },
  {
    text: "  const allY = series.flatMap(s => s.data.map(d => d.y));",
    color: "#d6d3d1",
  },
  { text: "", color: "" },
  { text: "  if (!allX.length || !allY.length)", color: "#d6d3d1" },
  { text: '    return <div className="flex h-[260px]', color: "#60a5fa" },
  { text: '      items-center justify-center">', color: "#60a5fa" },
  { text: "      No data available", color: "#a8a29e" },
  { text: "    </div>;", color: "#60a5fa" },
];

const FILE_TREE = [
  { name: "package.json", isDir: false, indent: 0 },
  { name: "tailwind.config.ts", isDir: false, indent: 0 },
  { name: "tsconfig.json", isDir: false, indent: 0 },
  { name: "app", isDir: true, indent: 0 },
  { name: "globals.css", isDir: false, indent: 1 },
  { name: "layout.tsx", isDir: false, indent: 1 },
  { name: "page.tsx", isDir: false, indent: 1, active: true },
  { name: "components", isDir: true, indent: 0 },
  { name: "LineChart.tsx", isDir: false, indent: 1, active: true },
  { name: "lib", isDir: true, indent: 0 },
  { name: "data.ts", isDir: false, indent: 1 },
];

// Chart path data — 480×140 SVG, padding 15/15/25/35
// 12 points: Feb 2020 → Jun 2026
const CHART_MAIN =
  "M 35 65 L 74 57 L 113 61 L 152 15 L 191 52 L 230 72 L 270 90 L 309 82 L 348 74 L 387 69 L 426 72 L 465 70";
const CHART_4WMA =
  "M 35 68 L 74 60 L 113 58 L 152 25 L 191 54 L 230 74 L 270 88 L 309 81 L 348 74 L 387 69 L 426 70 L 465 69";
const CHART_12WMA =
  "M 35 71 L 74 64 L 113 60 L 152 38 L 191 56 L 230 76 L 270 87 L 309 82 L 348 75 L 387 70 L 426 69 L 465 69";
const ANOMALY_DOTS = [
  { cx: 152, cy: 15 },
  { cx: 270, cy: 90 },
];

// ── Phase timing (ms each phase lasts before advancing) ───────────────────────
// 0=init → 1=steps+code → 2=artifact → 3=filetree → 4=starting → 5=preview → loop
const PHASE_MS: [number, number, number, number, number, number] = [
  300, 5600, 1800, 2200, 1200, 6000,
];

// ── Sub-components ────────────────────────────────────────────────────────────

function SkillIcon() {
  return (
    <svg
      viewBox="0 0 16 16"
      fill="none"
      className="size-3.5 shrink-0 text-stone-400"
    >
      <rect
        x="2"
        y="2"
        width="12"
        height="12"
        rx="2"
        stroke="currentColor"
        strokeWidth="1.3"
      />
      <path
        d="M5 5.5h6M5 8h4"
        stroke="currentColor"
        strokeWidth="1.3"
        strokeLinecap="round"
      />
    </svg>
  );
}

function EditIcon() {
  return (
    <svg
      viewBox="0 0 16 16"
      fill="none"
      className="size-3.5 shrink-0 text-stone-400"
    >
      <path
        d="M9.5 3.5l3 3-7 7H2.5v-3l7-7z"
        stroke="currentColor"
        strokeWidth="1.3"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function FolderIcon({ open }: { open?: boolean }) {
  return (
    <svg viewBox="0 0 16 16" fill="none" className="size-3 shrink-0">
      {open ? (
        <path
          d="M2 5a1 1 0 011-1h3l1.5 1.5H13a1 1 0 011 1V12a1 1 0 01-1 1H3a1 1 0 01-1-1V5z"
          fill="#fbbf24"
          stroke="#f59e0b"
          strokeWidth="0.8"
        />
      ) : (
        <path
          d="M2 4a1 1 0 011-1h3l1.5 1.5H13a1 1 0 011 1V11a1 1 0 01-1 1H3a1 1 0 01-1-1V4z"
          fill="#fde68a"
          stroke="#f59e0b"
          strokeWidth="0.8"
        />
      )}
    </svg>
  );
}

function FileDocIcon({ active }: { active?: boolean }) {
  return (
    <svg viewBox="0 0 16 16" fill="none" className="size-3 shrink-0">
      <path
        d="M4 2h5.5L12 4.5V14H4V2z"
        fill={active ? "#dbeafe" : "#f5f5f4"}
        stroke={active ? "#93c5fd" : "#d6d3d1"}
        strokeWidth="0.8"
      />
      <path
        d="M9 2v3h3"
        stroke={active ? "#93c5fd" : "#d6d3d1"}
        strokeWidth="0.8"
      />
    </svg>
  );
}

function GlobeIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" className="size-4 text-stone-500">
      <circle cx="10" cy="10" r="7.5" stroke="currentColor" strokeWidth="1.3" />
      <path
        d="M10 2.5c0 0-3 3-3 7.5s3 7.5 3 7.5M10 2.5c0 0 3 3 3 7.5s-3 7.5-3 7.5M2.5 10h15"
        stroke="currentColor"
        strokeWidth="1.3"
      />
    </svg>
  );
}

function EyeIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="none" className="size-3.5">
      <path
        d="M1.5 8s2.5-4.5 6.5-4.5S14.5 8 14.5 8s-2.5 4.5-6.5 4.5S1.5 8 1.5 8z"
        stroke="currentColor"
        strokeWidth="1.2"
      />
      <circle cx="8" cy="8" r="1.5" stroke="currentColor" strokeWidth="1.2" />
    </svg>
  );
}

function ChartIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="none" className="size-3.5">
      <polyline
        points="2,12 6,6 9,9 14,3"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function SettingsIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="none" className="size-3.5">
      <circle cx="8" cy="8" r="2" stroke="currentColor" strokeWidth="1.2" />
      <path
        d="M8 1v2M8 13v2M1 8h2M13 8h2M3.05 3.05l1.41 1.41M11.54 11.54l1.41 1.41M3.05 12.95l1.41-1.41M11.54 4.46l1.41-1.41"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinecap="round"
      />
    </svg>
  );
}

function PlayIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="none" className="size-3.5">
      <path d="M4 3l9 5-9 5V3z" fill="currentColor" />
    </svg>
  );
}

function ExternalLinkIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="none" className="size-3.5">
      <path
        d="M7 3H3v10h10V9M10 2h4v4M14 2l-6 6"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function DownloadIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="none" className="size-3.5">
      <path
        d="M8 2v8M5 7l3 3 3-3M3 13h10"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

// ── Chart SVG ─────────────────────────────────────────────────────────────────

function DashboardChart({ progress }: { progress: number }) {
  const dashoffset = String(Math.max(0, 1 - progress));
  return (
    <svg
      viewBox="0 0 480 140"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className="w-full"
      aria-hidden
    >
      {/* Grid lines */}
      {[15, 48, 81, 114].map((y) => (
        <line
          key={y}
          x1="35"
          y1={y}
          x2="465"
          y2={y}
          stroke="#f5f5f4"
          strokeWidth="1"
        />
      ))}
      {/* Y-axis labels */}
      {[
        { y: 17, label: "8.33" },
        { y: 50, label: "5.96" },
        { y: 83, label: "3.58" },
        { y: 116, label: "0.69" },
      ].map(({ y, label }) => (
        <text key={y} x="30" y={y} textAnchor="end" fontSize="8" fill="#a8a29e">
          {label}
        </text>
      ))}
      {/* X-axis labels */}
      {[
        { x: 35, label: "Feb 2020" },
        { x: 152, label: "Sep 2021" },
        { x: 270, label: "Feb 2023" },
        { x: 387, label: "Sep 2024" },
        { x: 465, label: "Jun 2026" },
      ].map(({ x, label }) => (
        <text
          key={x}
          x={x}
          y="133"
          textAnchor="middle"
          fontSize="7.5"
          fill="#a8a29e"
        >
          {label}
        </text>
      ))}

      {/* 12w MA (dashed yellow) */}
      <path
        d={CHART_12WMA}
        stroke="#fbbf24"
        strokeWidth="1.5"
        strokeDasharray="4 2"
        fill="none"
        pathLength="1"
        style={{ strokeDashoffset: dashoffset }}
      />
      {/* 4w MA (dashed green) */}
      <path
        d={CHART_4WMA}
        stroke="#34d399"
        strokeWidth="1.5"
        strokeDasharray="4 2"
        fill="none"
        pathLength="1"
        style={{ strokeDashoffset: dashoffset }}
      />
      {/* Base line (solid blue) */}
      <path
        d={CHART_MAIN}
        stroke="#3b82f6"
        strokeWidth="2"
        fill="none"
        pathLength="1"
        style={{ strokeDashoffset: dashoffset }}
      />
      {/* Anomaly dots (appear after chart draws) */}
      {progress > 0.85 &&
        ANOMALY_DOTS.map(({ cx, cy }) => (
          <circle
            key={`${cx}-${cy}`}
            cx={cx}
            cy={cy}
            r="4"
            fill="#ef4444"
            stroke="white"
            strokeWidth="1.5"
            style={{ opacity: Math.max(0, (progress - 0.85) / 0.15) }}
          />
        ))}
    </svg>
  );
}

// ── Preview Dashboard ─────────────────────────────────────────────────────────

function PreviewDashboard({ visible }: { visible: boolean }) {
  const [chartProgress, setChartProgress] = useState(0);
  const rafRef = useRef<number | null>(null);
  const startRef = useRef<number | null>(null);

  useEffect(() => {
    if (!visible) {
      setChartProgress(0);
      startRef.current = null;
      return;
    }
    const duration = 1800;
    const tick = (now: number) => {
      startRef.current ??= now;
      const p = Math.min((now - startRef.current) / duration, 1);
      setChartProgress(p);
      if (p < 1) rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [visible]);

  return (
    <div
      className={cn(
        "h-full overflow-y-auto bg-white px-5 py-4 transition-opacity duration-500",
        visible ? "opacity-100" : "opacity-0",
      )}
    >
      <h3 className="text-sm font-bold text-stone-900">Analytics Dashboard</h3>
      <p className="mt-0.5 text-[10px] leading-relaxed text-stone-400">
        Market Share %, Estimated Visits, and Visibility % with 4w/12w MAs and
        anomaly markers.
      </p>

      {/* Controls */}
      <div className="mt-3 flex items-center gap-3">
        <div className="flex items-center gap-1.5 rounded-md border border-stone-200 px-2 py-1 text-[10px] text-stone-600">
          Metric
          <span className="font-medium">Market Share %</span>
          <svg viewBox="0 0 10 10" className="size-2.5 fill-stone-400">
            <path
              d="M2 3.5l3 3 3-3"
              stroke="currentColor"
              strokeWidth="1.2"
              fill="none"
            />
          </svg>
        </div>
        <div className="flex items-center gap-1 text-[10px] text-stone-500">
          <span>Date range</span>
          {["1y", "2y", "3y"].map((r) => (
            <span
              key={r}
              className="rounded px-1.5 py-0.5 text-stone-400 hover:bg-stone-100"
            >
              {r}
            </span>
          ))}
          <span className="rounded bg-stone-900 px-1.5 py-0.5 text-white">
            max
          </span>
        </div>
      </div>

      {/* KPI cards */}
      <div
        className={cn(
          "mt-3 grid grid-cols-3 gap-2 transition-all duration-500",
          visible && chartProgress > 0.1
            ? "translate-y-0 opacity-100"
            : "translate-y-2 opacity-0",
        )}
      >
        {[
          {
            label: "Latest",
            value: "4.08%",
            sub: "▲ 0.00% WoW",
            subColor: "text-emerald-500",
          },
          { label: "4w MA", value: "4.17%", sub: "", subColor: "" },
          { label: "12w MA", value: "2.43%", sub: "", subColor: "" },
        ].map(({ label, value, sub, subColor }) => (
          <div
            key={label}
            className="rounded-lg border border-stone-100 bg-stone-50 px-3 py-2"
          >
            <p className="text-[9px] text-stone-400">{label}</p>
            <p className="mt-0.5 text-base leading-none font-bold text-stone-900">
              {value}
            </p>
            {sub && <p className={cn("mt-1 text-[9px]", subColor)}>{sub}</p>}
          </div>
        ))}
      </div>

      {/* Chart */}
      <div
        className={cn(
          "mt-3 rounded-lg border border-stone-100 p-3 transition-all duration-500",
          visible && chartProgress > 0.05 ? "opacity-100" : "opacity-0",
        )}
      >
        <div className="mb-1.5 flex items-center justify-between">
          <p className="text-[10px] font-medium text-stone-700">
            Market Share % over time
          </p>
          <div className="flex items-center gap-3 text-[8.5px] text-stone-400">
            <span className="flex items-center gap-1">
              <span className="inline-block h-0.5 w-4 bg-blue-500" /> Base
            </span>
            <span className="flex items-center gap-1">
              <span className="inline-block h-0.5 w-4 border-t-2 border-dashed border-emerald-400" />{" "}
              4w MA
            </span>
            <span className="flex items-center gap-1">
              <span className="inline-block h-0.5 w-4 border-t-2 border-dashed border-yellow-400" />{" "}
              12w MA
            </span>
            <span className="flex items-center gap-1">
              <span className="inline-block size-2 rounded-full bg-red-500" />{" "}
              Anomaly
            </span>
          </div>
        </div>
        <DashboardChart progress={chartProgress} />
      </div>
    </div>
  );
}

// ── Code Editor ───────────────────────────────────────────────────────────────

function CodeEditor({ visibleLines }: { visibleLines: number }) {
  return (
    <div className="h-full overflow-hidden bg-[#111111] px-4 py-3 font-mono">
      {CODE_LINES.slice(0, visibleLines).map((line, i) => (
        <div key={i} className="flex items-start">
          <span className="mr-3 w-4 shrink-0 text-right text-[10px] leading-[1.65] text-stone-600 select-none">
            {i + 1}
          </span>
          <span
            className="text-[11px] leading-[1.65] whitespace-pre"
            style={{ color: line.color || "#78716c" }}
          >
            {line.text || " "}
          </span>
          {i === visibleLines - 1 && (
            <span
              className="ml-px inline-block h-3.5 w-1.5 bg-stone-300"
              style={{ animation: "blink 1s step-end infinite" }}
            />
          )}
        </div>
      ))}
      <style>{`@keyframes blink { 0%,100%{opacity:1} 50%{opacity:0} }`}</style>
    </div>
  );
}

// ── File Tree View ────────────────────────────────────────────────────────────

function FileTreeView() {
  return (
    <div className="flex h-full">
      {/* Tree */}
      <div className="w-[140px] shrink-0 overflow-y-auto border-r border-stone-800 bg-[#1a1a1a] py-2">
        {FILE_TREE.map((item, i) => (
          <div
            key={i}
            className={cn(
              "flex cursor-default items-center gap-1 px-2 py-[2px] text-[10px]",
              item.indent === 1 ? "pl-5" : "pl-2",
              (item as { active?: boolean }).active
                ? "bg-stone-700 text-stone-200"
                : "text-stone-400 hover:bg-stone-800",
            )}
          >
            {item.isDir ? (
              <FolderIcon open />
            ) : (
              <FileDocIcon active={(item as { active?: boolean }).active} />
            )}
            <span className="truncate">{item.name}</span>
          </div>
        ))}
      </div>
      {/* Code panel */}
      <div className="flex-1 overflow-hidden bg-[#111111] px-4 py-3 font-mono">
        {CODE_LINES.slice(0, 20).map((line, i) => (
          <div key={i} className="flex items-start">
            <span className="mr-3 w-4 shrink-0 text-right text-[10px] leading-[1.65] text-stone-600 select-none">
              {i + 1}
            </span>
            <span
              className="text-[11px] leading-[1.65] whitespace-pre"
              style={{ color: line.color || "#78716c" }}
            >
              {line.text || " "}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Main Demo Component ───────────────────────────────────────────────────────

export function LivePreviewDemoSection({ className }: { className?: string }) {
  const [phase, setPhase] = useState(0);
  const [visibleSteps, setVisibleSteps] = useState(0);
  const [visibleCodeLines, setVisibleCodeLines] = useState(0);
  const [artifactClicked, setArtifactClicked] = useState(false);
  const [isInView, setIsInView] = useState(false);
  const sectionRef = useRef<HTMLDivElement>(null);
  const timeoutsRef = useRef<ReturnType<typeof setTimeout>[]>([]);

  // Intersection observer — only start when visible
  useEffect(() => {
    const el = sectionRef.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) setIsInView(true);
      },
      { threshold: 0.25 },
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, []);

  const clearAll = () => timeoutsRef.current.forEach(clearTimeout);

  const addTimeout = (fn: () => void, ms: number) => {
    const t = setTimeout(fn, ms);
    timeoutsRef.current.push(t);
    return t;
  };

  // Phase orchestration
  useEffect(() => {
    if (!isInView) return;
    clearAll();

    // Reset sub-states on phase change
    if (phase === 0) {
      setVisibleSteps(0);
      setVisibleCodeLines(0);
      setArtifactClicked(false);
      addTimeout(() => setPhase(1), PHASE_MS[0]);
      return;
    }

    if (phase === 1) {
      // Steps appear one by one
      STEPS.forEach((_, i) => {
        addTimeout(() => setVisibleSteps(i + 1), 300 + i * 950);
      });
      // Code lines stream in
      for (let i = 0; i < CODE_LINES.length; i++) {
        addTimeout(() => setVisibleCodeLines(i + 1), 200 + i * 140);
      }
      addTimeout(() => setPhase(2), PHASE_MS[1]);
      return;
    }

    if (phase === 2) {
      addTimeout(() => setPhase(3), PHASE_MS[2]);
      return;
    }

    if (phase === 3) {
      addTimeout(() => setArtifactClicked(true), 300);
      addTimeout(() => setPhase(4), PHASE_MS[3]);
      return;
    }

    if (phase === 4) {
      addTimeout(() => setPhase(5), PHASE_MS[4]);
      return;
    }

    if (phase === 5) {
      addTimeout(() => setPhase(0), PHASE_MS[5]);
      return;
    }

    return () => clearAll();
  }, [phase, isInView]);

  const isRunning = phase >= 5;
  const showPreview = phase === 5;
  const showFileTree = phase === 4 || phase === 5;
  const showCode = phase === 1 || phase === 2;
  const showArtifactCard = phase >= 2;
  const showAgentMessage = phase >= 2;

  return (
    <section
      ref={sectionRef}
      className={cn("mx-auto w-full max-w-6xl px-6 py-24", className)}
    >
      {/* Heading */}
      <div className="mb-12 flex flex-col items-center gap-3 text-center">
        <p className="text-xs font-semibold tracking-widest text-stone-400 uppercase">
          Live Preview
        </p>
        <h2 className="max-w-2xl text-4xl font-bold tracking-tight text-stone-900 md:text-5xl">
          Watch it build,{" "}
          <span className="text-stone-400">run, and verify itself</span>
        </h2>
        <p className="max-w-lg text-base leading-relaxed text-stone-500">
          The agent codes, the preview auto-starts, and the loop closes — no
          copy-paste relay required.
        </p>
      </div>

      {/* Browser window mockup */}
      <div className="overflow-hidden rounded-2xl border border-stone-200 shadow-2xl shadow-stone-200/60">
        {/* Browser chrome */}
        <div className="flex items-center gap-3 border-b border-stone-200 bg-stone-50 px-4 py-2.5">
          <div className="flex gap-1.5">
            <div className="size-2.5 rounded-full bg-red-400" />
            <div className="size-2.5 rounded-full bg-yellow-400" />
            <div className="size-2.5 rounded-full bg-green-400" />
          </div>
          <div className="flex flex-1 items-center justify-center">
            <div className="flex items-center gap-1.5 rounded-md border border-stone-200 bg-white px-3 py-1 text-[11px] text-stone-400">
              <svg viewBox="0 0 14 14" className="size-2.5 fill-stone-400">
                <path d="M7 1a6 6 0 100 12A6 6 0 007 1zm0 1.2a4.8 4.8 0 110 9.6 4.8 4.8 0 010-9.6z" />
              </svg>
              localhost:2026/workspace/chats/analytics-dashboard
            </div>
          </div>
        </div>

        {/* App shell */}
        <div className="flex h-[500px] bg-white">
          {/* Narrow sidebar */}
          <div className="flex w-10 shrink-0 flex-col items-center gap-4 border-r border-stone-100 bg-stone-50 py-4">
            <div className="flex size-5 items-center justify-center rounded-full bg-stone-900 text-[8px] font-bold text-white">
              O
            </div>
            {[
              <svg
                key="c"
                viewBox="0 0 16 16"
                fill="none"
                className="size-4 text-stone-400"
              >
                <path
                  d="M2 3h12v8H2z"
                  stroke="currentColor"
                  strokeWidth="1.2"
                  strokeLinejoin="round"
                />
                <path
                  d="M5 11v2M8 11v2M11 11v2"
                  stroke="currentColor"
                  strokeWidth="1.2"
                  strokeLinecap="round"
                />
              </svg>,
              <svg
                key="m"
                viewBox="0 0 16 16"
                fill="none"
                className="size-4 text-stone-400"
              >
                <circle
                  cx="8"
                  cy="6"
                  r="3"
                  stroke="currentColor"
                  strokeWidth="1.2"
                />
                <path
                  d="M2.5 14c0-2.5 2.5-4 5.5-4s5.5 1.5 5.5 4"
                  stroke="currentColor"
                  strokeWidth="1.2"
                  strokeLinecap="round"
                />
              </svg>,
              <svg
                key="a"
                viewBox="0 0 16 16"
                fill="none"
                className="size-4 text-stone-400"
              >
                <rect
                  x="2"
                  y="3"
                  width="5"
                  height="5"
                  rx="1"
                  stroke="currentColor"
                  strokeWidth="1.2"
                />
                <rect
                  x="9"
                  y="3"
                  width="5"
                  height="5"
                  rx="1"
                  stroke="currentColor"
                  strokeWidth="1.2"
                />
                <rect
                  x="2"
                  y="10"
                  width="5"
                  height="5"
                  rx="1"
                  stroke="currentColor"
                  strokeWidth="1.2"
                />
                <rect
                  x="9"
                  y="10"
                  width="5"
                  height="5"
                  rx="1"
                  stroke="currentColor"
                  strokeWidth="1.2"
                />
              </svg>,
            ]}
          </div>

          {/* Chat panel */}
          <div className="flex w-[44%] shrink-0 flex-col border-r border-stone-100">
            {/* Chat header */}
            <div className="flex items-center justify-between border-b border-stone-100 px-4 py-2.5">
              <span className="text-[11px] font-medium text-stone-700">
                Analytics Dashboard
              </span>
              <div className="flex items-center gap-2">
                <button className="flex items-center gap-1 rounded px-2 py-1 text-[10px] text-stone-400 hover:bg-stone-50">
                  <DownloadIcon /> Export
                </button>
                <button className="flex items-center gap-1 rounded px-2 py-1 text-[10px] text-stone-400 hover:bg-stone-50">
                  <svg viewBox="0 0 14 14" fill="none" className="size-3">
                    <rect
                      x="2"
                      y="2"
                      width="4"
                      height="4"
                      rx="0.5"
                      stroke="currentColor"
                      strokeWidth="1.1"
                    />
                    <rect
                      x="8"
                      y="2"
                      width="4"
                      height="4"
                      rx="0.5"
                      stroke="currentColor"
                      strokeWidth="1.1"
                    />
                    <rect
                      x="2"
                      y="8"
                      width="4"
                      height="4"
                      rx="0.5"
                      stroke="currentColor"
                      strokeWidth="1.1"
                    />
                    <rect
                      x="8"
                      y="8"
                      width="4"
                      height="4"
                      rx="0.5"
                      stroke="currentColor"
                      strokeWidth="1.1"
                    />
                  </svg>{" "}
                  Artifacts
                </button>
              </div>
            </div>

            {/* Scroll area */}
            <div className="flex-1 overflow-hidden px-4 py-3">
              {/* Steps accordion */}
              {visibleSteps > 0 && (
                <div className="rounded-xl border border-stone-100 bg-stone-50/70 p-3">
                  <button className="mb-2 flex items-center gap-1.5 text-[10px] text-stone-400">
                    <svg viewBox="0 0 12 12" fill="none" className="size-2.5">
                      <path
                        d="M2 4l4 4 4-4"
                        stroke="currentColor"
                        strokeWidth="1.2"
                      />
                    </svg>
                    Less steps
                  </button>
                  <div className="flex flex-col gap-2.5">
                    {STEPS.slice(0, visibleSteps).map((step, i) => (
                      <div
                        key={i}
                        className="animate-fadeIn flex flex-col gap-0.5"
                        style={{ animationDuration: "0.3s" }}
                      >
                        <div className="flex items-center gap-1.5 text-[10.5px] text-stone-700">
                          {step.type === "skill" ? <SkillIcon /> : <EditIcon />}
                          {step.label}
                          {i < visibleSteps - 1 && (
                            <svg
                              viewBox="0 0 12 12"
                              className="ml-auto size-3 text-emerald-500"
                              fill="currentColor"
                            >
                              <path
                                d="M2 6l3 3 5-5"
                                stroke="currentColor"
                                strokeWidth="1.5"
                                fill="none"
                                strokeLinecap="round"
                              />
                            </svg>
                          )}
                          {i === visibleSteps - 1 && (
                            <span className="ml-auto inline-flex gap-0.5">
                              {[0, 1, 2].map((j) => (
                                <span
                                  key={j}
                                  className="inline-block size-1 rounded-full bg-stone-400"
                                  style={{
                                    animation: `bounce 0.9s ${j * 0.2}s ease-in-out infinite`,
                                  }}
                                />
                              ))}
                            </span>
                          )}
                        </div>
                        <span className="ml-5 text-[9.5px] text-stone-400">
                          {step.path}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Agent message */}
              {showAgentMessage && (
                <div
                  className={cn(
                    "mt-3 text-[11px] leading-relaxed text-stone-700 transition-all duration-500",
                    showAgentMessage
                      ? "translate-y-0 opacity-100"
                      : "translate-y-2 opacity-0",
                  )}
                >
                  <p className="font-medium">
                    The dashboard is complete and the dev server is running.
                  </p>
                  <p className="mt-1.5 text-[10.5px] text-stone-500">
                    What I built
                  </p>
                  <ul className="mt-1 space-y-0.5 text-[10.5px] text-stone-500">
                    <li>• Next.js 14 app with Tailwind CSS</li>
                    <li>• SVG line chart with 4w/12w moving averages</li>
                    <li>• Anomaly detection with z-score markers</li>
                  </ul>
                </div>
              )}

              {/* Artifact card */}
              {showArtifactCard && (
                <div
                  className={cn(
                    "mt-3 cursor-pointer rounded-xl border transition-all duration-500",
                    artifactClicked
                      ? "border-stone-900 bg-stone-900 shadow-md"
                      : "border-stone-200 bg-white hover:border-stone-300",
                    showArtifactCard
                      ? "translate-y-0 opacity-100"
                      : "translate-y-4 opacity-0",
                  )}
                >
                  <div className="flex items-center gap-2.5 px-3 py-2.5">
                    <div
                      className={cn(
                        "flex size-7 shrink-0 items-center justify-center rounded-lg",
                        artifactClicked ? "bg-white/10" : "bg-stone-100",
                      )}
                    >
                      <span className={artifactClicked ? "text-white" : ""}>
                        <GlobeIcon />
                      </span>
                    </div>
                    <div className="min-w-0 flex-1">
                      <p
                        className={cn(
                          "truncate text-[11px] font-semibold",
                          artifactClicked ? "text-white" : "text-stone-800",
                        )}
                      >
                        Analytics Dashboard (Next.js 14)
                      </p>
                      <span
                        className={cn(
                          "mt-0.5 inline-block rounded px-1.5 py-0.5 text-[9px] font-medium",
                          artifactClicked
                            ? "bg-white/15 text-white/80"
                            : "bg-stone-100 text-stone-500",
                        )}
                      >
                        Live App
                      </span>
                    </div>
                    <button
                      className={cn(
                        "flex items-center gap-1 rounded px-1.5 py-1 text-[9.5px]",
                        artifactClicked ? "text-white/60" : "text-stone-400",
                      )}
                    >
                      <DownloadIcon />
                    </button>
                  </div>
                </div>
              )}
            </div>

            {/* Chat input */}
            <div className="border-t border-stone-100 px-3 py-2">
              <div className="rounded-xl border border-stone-200 bg-white px-3 py-2">
                <p className="text-[10.5px] text-stone-300">
                  How can I assist you today?
                </p>
                <div className="mt-2 flex items-center justify-between">
                  <div className="flex items-center gap-1 text-[10px] font-medium text-red-500">
                    <svg
                      viewBox="0 0 12 12"
                      fill="currentColor"
                      className="size-3"
                    >
                      <path d="M6 1l1 3h3l-2.5 2 1 3L6 7.5 3.5 9l1-3L2 4h3z" />
                    </svg>
                    Ultra
                  </div>
                  <div className="flex items-center gap-1 text-[10px] text-stone-400">
                    <span className="size-1.5 rounded-full bg-blue-500" />
                    OpenAI / GPT-5
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Artifact panel */}
          <div className="flex flex-1 flex-col bg-white">
            {/* Panel header */}
            <div className="flex items-center gap-2 border-b border-stone-100 px-3 py-2">
              <span className="truncate text-[11px] font-medium text-stone-700">
                Analytics Dashboard
              </span>
              <svg
                viewBox="0 0 12 12"
                fill="none"
                className="size-3 shrink-0 text-stone-400"
              >
                <path
                  d="M2 4l4 4 4-4"
                  stroke="currentColor"
                  strokeWidth="1.2"
                />
              </svg>

              {/* Status */}
              <div
                className={cn(
                  "flex items-center gap-1 rounded-full px-2 py-0.5 text-[9.5px] transition-all duration-500",
                  isRunning
                    ? "bg-emerald-50 text-emerald-600"
                    : "bg-stone-100 text-stone-400",
                )}
              >
                {isRunning ? (
                  <>
                    <span className="relative flex size-1.5">
                      <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
                      <span className="relative inline-flex size-1.5 rounded-full bg-emerald-500" />
                    </span>
                    running
                  </>
                ) : (
                  <>
                    <span className="size-1.5 rounded-full bg-stone-300" />
                    not running
                  </>
                )}
              </div>

              <div className="ml-auto flex items-center gap-0.5">
                {[
                  { icon: <EyeIcon />, active: true },
                  { icon: <ChartIcon />, active: false },
                  { icon: <SettingsIcon />, active: false },
                ].map(({ icon, active }, i) => (
                  <button
                    key={i}
                    className={cn(
                      "rounded p-1",
                      active
                        ? "bg-stone-100 text-stone-600"
                        : "text-stone-400 hover:bg-stone-50",
                    )}
                  >
                    {icon}
                  </button>
                ))}
                <div className="mx-1 h-3.5 w-px bg-stone-200" />
                {[
                  { icon: <ExternalLinkIcon /> },
                  {
                    icon: (
                      <span
                        className={cn(
                          "transition-colors duration-300",
                          phase === 4 ? "text-emerald-500" : "",
                        )}
                      >
                        <PlayIcon />
                      </span>
                    ),
                  },
                  { icon: <DownloadIcon /> },
                ].map(({ icon }, i) => (
                  <button
                    key={i}
                    className="rounded p-1 text-stone-400 hover:bg-stone-50"
                  >
                    {icon}
                  </button>
                ))}
              </div>
            </div>

            {/* Panel body */}
            <div className="relative flex-1 overflow-hidden">
              {/* Code editor */}
              <div
                className={cn(
                  "absolute inset-0 transition-opacity duration-300",
                  showCode ? "opacity-100" : "pointer-events-none opacity-0",
                )}
              >
                <CodeEditor visibleLines={showCode ? visibleCodeLines : 0} />
              </div>

              {/* File tree view */}
              <div
                className={cn(
                  "absolute inset-0 transition-opacity duration-300",
                  showFileTree && !showPreview
                    ? "opacity-100"
                    : "pointer-events-none opacity-0",
                )}
              >
                <FileTreeView />
              </div>

              {/* Live preview */}
              <div
                className={cn(
                  "absolute inset-0 transition-opacity duration-500",
                  showPreview ? "opacity-100" : "pointer-events-none opacity-0",
                )}
              >
                <PreviewDashboard visible={showPreview} />
              </div>
            </div>
          </div>
        </div>
      </div>

      <style>{`
        @keyframes bounce {
          0%, 100% { transform: translateY(0); }
          50% { transform: translateY(-3px); }
        }
        @keyframes fadeIn {
          from { opacity: 0; transform: translateY(4px); }
          to   { opacity: 1; transform: translateY(0); }
        }
        .animate-fadeIn { animation: fadeIn 0.3s ease-out forwards; }
      `}</style>
    </section>
  );
}
