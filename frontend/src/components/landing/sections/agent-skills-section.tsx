"use client";

import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

function AgentHarnessDiagram() {
  const paths = {
    taskToCore: "M360,40 L360,88",
    skillsToCore: "M116,88 C176,88 214,114 248,134",
    mcpToCore: "M116,144 C174,144 210,148 248,152",
    memoryToCore: "M116,200 C174,200 210,184 248,170",
    flowsToCore: "M360,248 L360,222",
    coreToSubA: "M472,144 C520,122 556,102 596,88",
    coreToSubB: "M472,154 L596,154",
    coreToSubC: "M472,164 C520,186 556,206 596,220",
    coreToSandbox: "M360,198 L360,242",
    coreToOutputs: "M632,154 L690,154",
  };

  const particles: Array<{ path: string; dur: string; begin: string }> = [
    { path: paths.taskToCore, dur: "1.1s", begin: "0s" },
    { path: paths.skillsToCore, dur: "1.4s", begin: "0.3s" },
    { path: paths.mcpToCore, dur: "1.4s", begin: "0.6s" },
    { path: paths.memoryToCore, dur: "1.4s", begin: "0.9s" },
    { path: paths.flowsToCore, dur: "0.9s", begin: "1.2s" },
    { path: paths.coreToSubA, dur: "1.1s", begin: "0.4s" },
    { path: paths.coreToSubB, dur: "0.9s", begin: "0.8s" },
    { path: paths.coreToSubC, dur: "1.1s", begin: "1.1s" },
    { path: paths.coreToOutputs, dur: "0.8s", begin: "1.3s" },
    { path: paths.coreToSandbox, dur: "0.9s", begin: "1.5s" },
  ];

  const leftNodes = [
    { x: 24, y: 68, label: "Skills" },
    { x: 24, y: 124, label: "MCP Tools" },
    { x: 24, y: 180, label: "Memory" },
  ];

  const subAgents = [
    { cx: 620, cy: 88, label: "01" },
    { cx: 620, cy: 154, label: "02" },
    { cx: 620, cy: 220, label: "03" },
  ];

  return (
    <svg
      viewBox="0 0 760 320"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className="w-full"
      aria-hidden
    >
      {Object.entries(paths).map(([key, d]) => (
        <path key={key} d={d} stroke="#e7e5e4" strokeWidth="1.5" />
      ))}

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

      <rect x="286" y="14" width="148" height="34" rx="17" fill="#111827" />
      <text
        x="360"
        y="35"
        textAnchor="middle"
        dominantBaseline="middle"
        fill="white"
        fontSize="10"
        fontFamily="ui-sans-serif,system-ui,sans-serif"
        fontWeight="500"
      >
        User Task
      </text>

      <rect x="248" y="116" width="224" height="84" rx="24" fill="#111827" />
      <rect
        x="248"
        y="116"
        width="224"
        height="84"
        rx="24"
        fill="none"
        stroke="#9ca3af"
        strokeWidth="1"
      >
        <animate
          attributeName="stroke-opacity"
          values="0.5;0.12;0.5"
          dur="2.4s"
          repeatCount="indefinite"
        />
      </rect>
      <text
        x="360"
        y="150"
        textAnchor="middle"
        dominantBaseline="middle"
        fill="white"
        fontSize="13"
        fontFamily="ui-sans-serif,system-ui,sans-serif"
        fontWeight="600"
      >
        Harness Control Plane
      </text>
      <text
        x="360"
        y="170"
        textAnchor="middle"
        dominantBaseline="middle"
        fill="#cbd5e1"
        fontSize="10"
        fontFamily="ui-sans-serif,system-ui,sans-serif"
      >
        Agent runtime · routing · policy · execution
      </text>

      {leftNodes.map(({ x, y, label }) => (
        <g key={label}>
          <circle cx={x + 38} cy={y + 16} r="3" fill="#111827" />
          <rect
            x={x}
            y={y}
            width="92"
            height="32"
            rx="16"
            fill="#f5f5f4"
            stroke="#1c1917"
            strokeWidth="1.5"
          />
          <text
            x={x + 46}
            y={y + 19}
            textAnchor="middle"
            dominantBaseline="middle"
            fill="#111827"
            fontSize="10"
            fontFamily="ui-sans-serif,system-ui,sans-serif"
            fontWeight="500"
          >
            {label}
          </text>
        </g>
      ))}

      <rect
        x="302"
        y="248"
        width="116"
        height="38"
        rx="19"
        fill="#f5f5f4"
        stroke="#1c1917"
        strokeWidth="1.5"
      />
      <text
        x="360"
        y="270"
        textAnchor="middle"
        dominantBaseline="middle"
        fill="#111827"
        fontSize="10"
        fontFamily="ui-sans-serif,system-ui,sans-serif"
        fontWeight="500"
      >
        Workflows
      </text>

      <rect
        x="512"
        y="138"
        width="92"
        height="32"
        rx="16"
        fill="#f5f5f4"
        stroke="#1c1917"
        strokeWidth="1.5"
      />
      <text
        x="558"
        y="157"
        textAnchor="middle"
        dominantBaseline="middle"
        fill="#111827"
        fontSize="10"
        fontFamily="ui-sans-serif,system-ui,sans-serif"
        fontWeight="500"
      >
        Sub-agents
      </text>

      {subAgents.map(({ cx, cy, label }) => (
        <g key={label}>
          <circle
            cx={cx}
            cy={cy}
            r="20"
            fill="#ffffff"
            stroke="#1c1917"
            strokeWidth="1.5"
          />
          <text
            x={cx}
            y={cy - 4}
            textAnchor="middle"
            dominantBaseline="middle"
            fill="#94a3b8"
            fontSize="7"
            fontFamily="ui-sans-serif,system-ui,sans-serif"
          >
            agent
          </text>
          <text
            x={cx}
            y={cy + 8}
            textAnchor="middle"
            dominantBaseline="middle"
            fill="#111827"
            fontSize="9"
            fontFamily="ui-monospace,monospace"
            fontWeight="600"
          >
            {label}
          </text>
        </g>
      ))}

      <rect x="690" y="110" width="52" height="32" rx="12" fill="#111827" />
      <text
        x="716"
        y="129"
        textAnchor="middle"
        dominantBaseline="middle"
        fill="white"
        fontSize="8.5"
        fontFamily="ui-sans-serif,system-ui,sans-serif"
        fontWeight="600"
      >
        Preview
      </text>

      <rect
        x="690"
        y="150"
        width="52"
        height="32"
        rx="12"
        fill="#f5f5f4"
        stroke="#1c1917"
        strokeWidth="1.5"
      />
      <text
        x="716"
        y="169"
        textAnchor="middle"
        dominantBaseline="middle"
        fill="#111827"
        fontSize="8.5"
        fontFamily="ui-sans-serif,system-ui,sans-serif"
        fontWeight="600"
      >
        Logs
      </text>

      <rect
        x="690"
        y="190"
        width="52"
        height="32"
        rx="12"
        fill="#f5f5f4"
        stroke="#1c1917"
        strokeWidth="1.5"
      />
      <text
        x="716"
        y="209"
        textAnchor="middle"
        dominantBaseline="middle"
        fill="#111827"
        fontSize="8.5"
        fontFamily="ui-sans-serif,system-ui,sans-serif"
        fontWeight="600"
      >
        Artifacts
      </text>

      <rect
        x="302"
        y="278"
        width="116"
        height="28"
        rx="14"
        fill="#ffffff"
        stroke="#d6d3d1"
        strokeWidth="1.25"
      />
      <text
        x="360"
        y="294"
        textAnchor="middle"
        dominantBaseline="middle"
        fill="#6b7280"
        fontSize="9"
        fontFamily="ui-sans-serif,system-ui,sans-serif"
      >
        Sandboxed execution
      </text>
    </svg>
  );
}

type LogLine = {
  text: string;
  delay: number;
  type?: "cmd" | "tool" | "result" | "ok" | "info" | "blank";
};

const LOG_LINES: LogLine[] = [
  {
    text: '$ omniharness run "Build a retention dashboard harness"',
    delay: 0,
    type: "cmd",
  },
  { text: "", delay: 500, type: "blank" },
  {
    text: "1. task understood -> analytics workbench",
    delay: 900,
    type: "info",
  },
  {
    text: "2. loading skills: codegen, charts, deployment",
    delay: 1300,
    type: "info",
  },
  {
    text: "3. connecting MCP tools: postgres, slack, github",
    delay: 1800,
    type: "tool",
  },
  { text: "", delay: 2900, type: "blank" },
  { text: "4. spawning 3 sub-agents in parallel", delay: 3200, type: "info" },
  { text: "   [agent:01] schema + data contracts", delay: 3500 },
  { text: "   [agent:02] charts + dashboard UI", delay: 3800 },
  { text: "   [agent:03] alert workflow + reporting", delay: 4100 },
  { text: "", delay: 4200, type: "blank" },
  {
    text: "5. write_file('/workspace/retention-app/app/page.tsx')",
    delay: 4500,
    type: "tool",
  },
  {
    text: "6. starting sandbox preview session on port 3000",
    delay: 5100,
    type: "tool",
  },
  {
    text: "7. preview healthcheck failed -> repairing import path",
    delay: 5700,
    type: "tool",
  },
  { text: "", delay: 6200, type: "blank" },
  {
    text: "8. live preview reachable at /artifacts/retention-app",
    delay: 6500,
    type: "result",
  },
  {
    text: "9. logs + artifacts attached to the harness",
    delay: 7000,
    type: "result",
  },
  { text: "", delay: 7200, type: "blank" },
  {
    text: "10. packaging harness for reuse + scheduled refresh",
    delay: 7600,
    type: "info",
  },
  {
    text: "   retention-app/  preview.log  workflow.yaml",
    delay: 8200,
    type: "ok",
  },
  { text: "", delay: 8600, type: "blank" },
  {
    text: "Harness ready - preview, inspect, reuse, automate",
    delay: 9000,
    type: "ok",
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
      <div
        ref={scrollRef}
        className="h-80 overflow-y-auto p-4 font-mono text-xs leading-5 [scrollbar-width:none] sm:h-96"
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

const HARNESS_STEPS = [
  "Understand the task",
  "Select the right skills and tools",
  "Delegate to sub-agents",
  "Write and run code in a sandbox",
  "Connect MCP tools",
  "Create project artifacts",
  "Preview live apps",
  "Inspect logs and files",
  "Repair failures",
  "Package, reuse, or schedule the result",
];

export function AgentSkillsSection({ className }: { className?: string }) {
  return (
    <section
      id="orchestration"
      className={cn(
        "mx-auto w-full max-w-6xl px-4 py-20 sm:px-6 sm:py-24",
        className,
      )}
    >
      <div className="mb-14 flex flex-col items-center gap-3 text-center">
        <p className="text-xs font-semibold tracking-widest text-stone-400 uppercase">
          From chat to capability
        </p>
        <h2 className="max-w-3xl text-4xl font-bold tracking-tight text-balance text-stone-950 md:text-5xl">
          Chat is the interface.{" "}
          <span className="text-stone-400">Harnesses are the output.</span>
        </h2>
        <p className="max-w-3xl text-base leading-relaxed text-pretty text-stone-500">
          Ask OmniHarness to build or operate something. It can route work
          across skills, MCP tools, sub-agents, workflows, memory, sandboxes,
          logs, and live previews without collapsing everything into a single
          response.
        </p>
      </div>

      <div className="grid items-start gap-6 xl:grid-cols-[1.15fr_0.85fr]">
        <div className="flex flex-col gap-4 rounded-3xl border border-stone-200 bg-white p-5 shadow-[0_16px_40px_rgba(15,23,42,0.04)] sm:p-6">
          <p className="text-xs font-medium tracking-widest text-stone-400 uppercase">
            How the harness orchestrates
          </p>
          <AgentHarnessDiagram />
          <div className="mt-1 flex flex-wrap gap-4 text-xs text-stone-400">
            <span className="flex items-center gap-1.5">
              <span className="inline-block h-2 w-2 rounded-full bg-stone-900" />
              Control plane
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

        <AgentLogWindow />
      </div>

      <div className="mt-8 grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        {HARNESS_STEPS.map((step, index) => (
          <div
            key={step}
            className="rounded-2xl border border-stone-200 bg-stone-50/70 px-4 py-3 text-sm text-stone-700"
          >
            <span className="mb-2 inline-flex size-6 items-center justify-center rounded-full bg-stone-900 text-[11px] font-semibold text-white">
              {index + 1}
            </span>
            <p className="leading-relaxed">{step}</p>
          </div>
        ))}
      </div>
    </section>
  );
}
