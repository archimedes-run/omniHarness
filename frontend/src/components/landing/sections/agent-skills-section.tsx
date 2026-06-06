"use client";

import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

// ── Architecture SVG ──────────────────────────────────────────────────────────

function AgentHarnessDiagram() {
  const p = {
    taskToLead: "M220,38 L220,85",
    skillsToLead: "M95,78 C148,78 186,97 187,108",
    memoryToLead: "M95,194 C148,194 186,141 187,128",
    leadToSub1: "M248,104 C298,88 316,74 333,74",
    leadToSub2: "M250,118 L333,118",
    leadToSub3: "M248,132 C298,148 316,162 333,162",
    sub1ToArt: "M377,74 C398,74 404,110 408,118",
    sub2ToArt: "M377,118 L408,118",
    sub3ToArt: "M377,162 C398,162 404,126 408,118",
  };

  const particles: Array<{ path: string; dur: string; begin: string }> = [
    { path: p.taskToLead, dur: "1.1s", begin: "0s" },
    { path: p.skillsToLead, dur: "1.6s", begin: "0.4s" },
    { path: p.memoryToLead, dur: "1.6s", begin: "1.0s" },
    { path: p.leadToSub1, dur: "1.2s", begin: "0.2s" },
    { path: p.leadToSub2, dur: "1.0s", begin: "0.6s" },
    { path: p.leadToSub3, dur: "1.2s", begin: "1.1s" },
    { path: p.sub1ToArt, dur: "1.1s", begin: "0.3s" },
    { path: p.sub2ToArt, dur: "0.8s", begin: "0.8s" },
    { path: p.sub3ToArt, dur: "1.1s", begin: "1.3s" },
  ];

  return (
    <svg
      viewBox="0 0 440 248"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className="w-full"
      aria-hidden
    >
      {/* Connection lines */}
      {Object.entries(p).map(([k, d]) => (
        <path key={k} d={d} stroke="#e7e5e4" strokeWidth="1.5" />
      ))}

      {/* Flowing particles */}
      {particles.map(({ path, dur, begin }, i) => (
        <circle key={i} r="2.5" cx="0" cy="0" fill="#a8a29e">
          <animateMotion
            path={path}
            dur={dur}
            begin={begin}
            repeatCount="indefinite"
          />
        </circle>
      ))}

      {/* Task input */}
      <rect x="165" y="8" width="110" height="30" rx="15" fill="#1c1917" />
      <text
        x="220"
        y="27"
        textAnchor="middle"
        dominantBaseline="middle"
        fill="white"
        fontSize="9.5"
        fontFamily="ui-sans-serif,system-ui,sans-serif"
        fontWeight="500"
      >
        User Task
      </text>

      {/* Lead Agent */}
      <circle cx="220" cy="118" r="33" fill="#1c1917" />
      <circle
        cx="220"
        cy="118"
        r="33"
        fill="none"
        stroke="#78716c"
        strokeWidth="1"
      >
        <animate
          attributeName="r"
          values="33;41;33"
          dur="2.8s"
          repeatCount="indefinite"
        />
        <animate
          attributeName="stroke-opacity"
          values="0.5;0;0.5"
          dur="2.8s"
          repeatCount="indefinite"
        />
      </circle>
      <text
        x="220"
        y="113"
        textAnchor="middle"
        dominantBaseline="middle"
        fill="white"
        fontSize="9"
        fontFamily="ui-sans-serif,system-ui,sans-serif"
      >
        Lead
      </text>
      <text
        x="220"
        y="125"
        textAnchor="middle"
        dominantBaseline="middle"
        fill="#a8a29e"
        fontSize="8"
        fontFamily="ui-sans-serif,system-ui,sans-serif"
      >
        Agent
      </text>

      {/* Skills pill */}
      <rect
        x="15"
        y="64"
        width="80"
        height="28"
        rx="14"
        fill="#f5f5f4"
        stroke="#1c1917"
        strokeWidth="1.5"
      />
      <text
        x="55"
        y="81"
        textAnchor="middle"
        dominantBaseline="middle"
        fill="#1c1917"
        fontSize="9"
        fontFamily="ui-sans-serif,system-ui,sans-serif"
        fontWeight="500"
      >
        Skills
      </text>

      {/* Memory pill */}
      <rect
        x="15"
        y="180"
        width="80"
        height="28"
        rx="14"
        fill="#f5f5f4"
        stroke="#1c1917"
        strokeWidth="1.5"
      />
      <text
        x="55"
        y="197"
        textAnchor="middle"
        dominantBaseline="middle"
        fill="#1c1917"
        fontSize="9"
        fontFamily="ui-sans-serif,system-ui,sans-serif"
        fontWeight="500"
      >
        Memory
      </text>

      {/* Sub-agents */}
      {(
        [
          { cx: 355, cy: 74, label: "01" },
          { cx: 355, cy: 118, label: "02" },
          { cx: 355, cy: 162, label: "03" },
        ] as const
      ).map(({ cx, cy, label }) => (
        <g key={label}>
          <circle
            cx={cx}
            cy={cy}
            r="22"
            fill="#f5f5f4"
            stroke="#1c1917"
            strokeWidth="1.5"
          />
          <text
            x={cx}
            y={cy - 5}
            textAnchor="middle"
            dominantBaseline="middle"
            fill="#a8a29e"
            fontSize="7"
            fontFamily="ui-sans-serif,system-ui,sans-serif"
          >
            agent
          </text>
          <text
            x={cx}
            y={cy + 7}
            textAnchor="middle"
            dominantBaseline="middle"
            fill="#1c1917"
            fontSize="9"
            fontFamily="ui-monospace,monospace"
            fontWeight="600"
          >
            {label}
          </text>
        </g>
      ))}

      {/* Artifacts — stacked doc rectangles */}
      <rect
        x="414"
        y="106"
        width="20"
        height="24"
        rx="2"
        fill="#e7e5e4"
        stroke="#d6d3d1"
        strokeWidth="1"
      />
      <rect
        x="411"
        y="110"
        width="20"
        height="24"
        rx="2"
        fill="#f5f5f4"
        stroke="#a8a29e"
        strokeWidth="1"
      />
      <rect
        x="408"
        y="114"
        width="20"
        height="24"
        rx="2"
        fill="white"
        stroke="#1c1917"
        strokeWidth="1.5"
      />
    </svg>
  );
}

// ── Agent Log Terminal ────────────────────────────────────────────────────────

type LogLine = {
  text: string;
  delay: number;
  type?: "cmd" | "tool" | "result" | "ok" | "info" | "blank";
};

const LOG_LINES: LogLine[] = [
  {
    text: '$ omniharness run "Research CRISPR delivery advances,',
    delay: 0,
    type: "cmd",
  },
  {
    text: '    generate investor brief with visualisations"',
    delay: 0,
    type: "cmd",
  },
  { text: "", delay: 500, type: "blank" },
  { text: "✦ Lead agent initialised", delay: 900, type: "info" },
  { text: "✦ Scanning skill library...", delay: 1300, type: "info" },
  { text: "  └─ research/SKILL.md", delay: 1700 },
  { text: "  └─ chart-visualization/SKILL.md", delay: 2100 },
  { text: "  └─ report-generation/SKILL.md", delay: 2500 },
  { text: "", delay: 2900, type: "blank" },
  { text: "✦ Spawning 2 sub-agents in parallel", delay: 3200, type: "info" },
  { text: "  ├─ [agent:01] literature + patent search", delay: 3600 },
  { text: "  └─ [agent:02] data visualisation", delay: 3900 },
  { text: "", delay: 4200, type: "blank" },
  {
    text: '  tool_call: web_search("CRISPR LNP delivery mechanisms 2025")',
    delay: 4500,
    type: "tool",
  },
  {
    text: '  tool_call: web_fetch("nature.com/articles/s41587-025...")',
    delay: 5100,
    type: "tool",
  },
  {
    text: '  tool_call: execute_python("plot_trial_outcomes.py")',
    delay: 5700,
    type: "tool",
  },
  { text: "", delay: 6200, type: "blank" },
  {
    text: "  [agent:01] 18 papers indexed, 4 patents found",
    delay: 6500,
    type: "result",
  },
  {
    text: "  [agent:02] trial_outcomes.png generated",
    delay: 6900,
    type: "result",
  },
  { text: "", delay: 7200, type: "blank" },
  { text: "✦ Synthesising, drafting brief...", delay: 7500, type: "info" },
  { text: "  write_file('investor_brief.md') ✓", delay: 8000, type: "ok" },
  { text: "  write_file('trial_outcomes.png') ✓", delay: 8300, type: "ok" },
  { text: "", delay: 8600, type: "blank" },
  { text: "✓ Complete — 3 artifacts ready", delay: 9000, type: "ok" },
  {
    text: "  investor_brief.md  ·  trial_outcomes.png  ·  sources.json",
    delay: 9400,
  },
];

const LINE_COLOR: Partial<Record<NonNullable<LogLine["type"]>, string>> = {
  cmd: "text-stone-100",
  info: "text-stone-300",
  tool: "text-emerald-400/80",
  result: "text-sky-400/80",
  ok: "text-emerald-400",
};

function AgentLogWindow() {
  const [visible, setVisible] = useState(0);
  const [running, setRunning] = useState(false);
  const timerIds = useRef<ReturnType<typeof setTimeout>[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);

  const clearAll = () => {
    timerIds.current.forEach(clearTimeout);
    timerIds.current = [];
  };

  const play = () => {
    clearAll();
    setVisible(0);
    setRunning(true);
    const ids: ReturnType<typeof setTimeout>[] = [];

    LOG_LINES.forEach((line, i) => {
      ids.push(
        setTimeout(() => {
          setVisible((n) => Math.max(n, i + 1));
          if (scrollRef.current) {
            scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
          }
        }, line.delay),
      );
    });

    const lastLine = LOG_LINES[LOG_LINES.length - 1];
    const restartAt = (lastLine?.delay ?? 0) + 3500;
    ids.push(setTimeout(play, restartAt));
    timerIds.current = ids;
  };

  useEffect(() => {
    play();
    return clearAll;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="flex flex-col overflow-hidden rounded-2xl border border-stone-800 bg-stone-950 shadow-xl shadow-stone-900/10">
      {/* Window chrome */}
      <div className="flex items-center justify-between border-b border-stone-800 px-4 py-3">
        <div className="flex gap-1.5">
          <div className="h-2.5 w-2.5 rounded-full bg-stone-700" />
          <div className="h-2.5 w-2.5 rounded-full bg-stone-700" />
          <div className="h-2.5 w-2.5 rounded-full bg-stone-700" />
        </div>
        <span className="font-mono text-xs text-stone-600">
          omniharness · agent log
        </span>
        <button
          onClick={() => {
            if (running) {
              clearAll();
              setRunning(false);
            } else {
              play();
            }
          }}
          className="text-xs text-stone-600 transition-colors hover:text-stone-400"
        >
          {running ? "pause" : "replay"}
        </button>
      </div>
      {/* Log output */}
      <div
        ref={scrollRef}
        className="h-80 overflow-y-auto p-4 font-mono text-xs leading-5 [scrollbar-width:none]"
      >
        {LOG_LINES.slice(0, visible).map((line, i) => (
          <div
            key={i}
            className={cn(
              "whitespace-pre",
              line.type
                ? (LINE_COLOR[line.type] ?? "text-stone-500")
                : "text-stone-500",
            )}
          >
            {line.text || " "}
          </div>
        ))}
        {running && visible < LOG_LINES.length && visible > 0 && (
          <span className="inline-block h-[11px] w-1.5 animate-pulse bg-stone-500" />
        )}
      </div>
    </div>
  );
}

// ── Section export ────────────────────────────────────────────────────────────

export function AgentSkillsSection({ className }: { className?: string }) {
  return (
    <section className={cn("mx-auto w-full max-w-5xl px-6 py-24", className)}>
      <div className="mb-14 flex flex-col items-center gap-3 text-center">
        <p className="text-xs font-semibold tracking-widest text-stone-400 uppercase">
          Agent Skills
        </p>
        <h2 className="max-w-2xl text-4xl font-bold tracking-tight text-stone-900 md:text-5xl">
          The right capability,{" "}
          <span className="text-stone-400">right when it&apos;s needed</span>
        </h2>
        <p className="max-w-lg text-base leading-relaxed text-stone-500">
          Skills load progressively — scoped to the task, not the session.
          Extend the built-in library with your own or the community&apos;s.
        </p>
      </div>

      <div className="grid items-start gap-6 lg:grid-cols-2">
        {/* Architecture diagram in a light card */}
        <div className="flex flex-col gap-2 rounded-2xl border border-stone-200 bg-white p-6">
          <p className="text-xs font-medium tracking-widest text-stone-400 uppercase">
            How the harness orchestrates
          </p>
          <AgentHarnessDiagram />
          <div className="mt-2 flex flex-wrap gap-4 text-xs text-stone-400">
            <span className="flex items-center gap-1.5">
              <span className="inline-block h-2 w-2 rounded-full bg-stone-900" />
              Lead Agent
            </span>
            <span className="flex items-center gap-1.5">
              <span className="inline-block h-2 w-2 rounded-full border border-stone-400" />
              Sub-Agents
            </span>
            <span className="flex items-center gap-1.5">
              <span className="inline-block h-1 w-4 bg-stone-300" />
              Data flow
            </span>
          </div>
        </div>

        {/* Live agent log */}
        <AgentLogWindow />
      </div>
    </section>
  );
}
