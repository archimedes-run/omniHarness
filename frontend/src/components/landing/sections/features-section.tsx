import { cn } from "@/lib/utils";

// ── Animated SVG icons — SMIL native animations, no JS runtime needed ─────────

function AgentOrchestrationIcon() {
  const spokes = [0, 1, 2, 3, 4].map((i) => {
    const a = (i * 2 * Math.PI) / 5 - Math.PI / 2;
    return {
      x: parseFloat((20 + 11 * Math.cos(a)).toFixed(1)),
      y: parseFloat((20 + 11 * Math.sin(a)).toFixed(1)),
    };
  });
  return (
    <svg
      viewBox="0 0 40 40"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className="h-6 w-6"
    >
      {spokes.map((s, i) => (
        <line
          key={`sl-${i}`}
          x1="20"
          y1="20"
          x2={s.x}
          y2={s.y}
          stroke="#a8a29e"
          strokeWidth="1"
          strokeDasharray="2 3"
        >
          <animate
            attributeName="stroke-dashoffset"
            from="0"
            to="-5"
            dur={`${0.5 + i * 0.1}s`}
            repeatCount="indefinite"
          />
        </line>
      ))}
      {spokes.map((s, i) => (
        <circle key={`sn-${i}`} cx={s.x} cy={s.y} r="2.5" fill="#78716c">
          <animate
            attributeName="opacity"
            values="0.4;1;0.4"
            dur={`${1.2 + i * 0.2}s`}
            repeatCount="indefinite"
          />
        </circle>
      ))}
      <circle cx="20" cy="20" r="5" fill="#1c1917" />
      <circle
        cx="20"
        cy="20"
        r="5"
        fill="none"
        stroke="#78716c"
        strokeWidth="1.5"
      >
        <animate
          attributeName="r"
          values="5;9.5;5"
          dur="2s"
          repeatCount="indefinite"
        />
        <animate
          attributeName="stroke-opacity"
          values="0.6;0;0.6"
          dur="2s"
          repeatCount="indefinite"
        />
      </circle>
    </svg>
  );
}

function SandboxIcon() {
  return (
    <svg
      viewBox="0 0 40 40"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className="h-6 w-6"
    >
      <rect
        x="3"
        y="5"
        width="34"
        height="30"
        rx="3"
        stroke="#1c1917"
        strokeWidth="1.5"
      />
      <line x1="3" y1="13" x2="37" y2="13" stroke="#1c1917" strokeWidth="1" />
      <circle cx="8.5" cy="9" r="1.3" fill="#d6d3d1" />
      <circle cx="13" cy="9" r="1.3" fill="#d6d3d1" />
      <circle cx="17.5" cy="9" r="1.3" fill="#d6d3d1" />
      {/* Code line 1 types in */}
      <rect x="7" y="18" width="0" height="1.5" rx="0.75" fill="#1c1917">
        <animate
          attributeName="width"
          values="0;16;16;16;0"
          keyTimes="0;0.15;0.55;0.85;1"
          dur="3s"
          repeatCount="indefinite"
        />
      </rect>
      {/* Code line 2 types in */}
      <rect x="7" y="22.5" width="0" height="1.5" rx="0.75" fill="#78716c">
        <animate
          attributeName="width"
          values="0;0;22;22;0"
          keyTimes="0;0.2;0.45;0.85;1"
          dur="3s"
          repeatCount="indefinite"
        />
      </rect>
      {/* Code line 3 types in */}
      <rect x="7" y="27" width="0" height="1.5" rx="0.75" fill="#78716c">
        <animate
          attributeName="width"
          values="0;0;0;12;0"
          keyTimes="0;0.35;0.55;0.75;1"
          dur="3s"
          repeatCount="indefinite"
        />
      </rect>
      {/* Blinking cursor */}
      <rect x="20.5" y="27" width="1.2" height="1.5" rx="0.3" fill="#1c1917">
        <animate
          attributeName="opacity"
          values="0;0;0;1;0;1;0;1;0;0"
          keyTimes="0;0.35;0.55;0.58;0.63;0.67;0.72;0.76;0.85;1"
          dur="3s"
          repeatCount="indefinite"
        />
      </rect>
    </svg>
  );
}

function MemoryIcon() {
  return (
    <svg
      viewBox="0 0 40 40"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className="h-6 w-6"
    >
      {/* Cylinder walls */}
      <line x1="8" y1="12" x2="8" y2="30" stroke="#1c1917" strokeWidth="1.5" />
      <line
        x1="32"
        y1="12"
        x2="32"
        y2="30"
        stroke="#1c1917"
        strokeWidth="1.5"
      />
      {/* Bottom cap */}
      <ellipse
        cx="20"
        cy="30"
        rx="12"
        ry="3.5"
        fill="#e7e5e4"
        stroke="#1c1917"
        strokeWidth="1.5"
      />
      {/* Middle data layer */}
      <ellipse
        cx="20"
        cy="21"
        rx="12"
        ry="3.5"
        fill="#ede9e7"
        stroke="#d6d3d1"
        strokeWidth="1"
      />
      {/* Top cap */}
      <ellipse
        cx="20"
        cy="12"
        rx="12"
        ry="3.5"
        fill="#d6d3d1"
        stroke="#1c1917"
        strokeWidth="1.5"
      />
      {/* Write dot descends into the database */}
      <circle cx="20" cy="12" r="2.5" fill="#1c1917">
        <animate
          attributeName="cy"
          values="9;32;32;9"
          keyTimes="0;0.42;0.55;1"
          dur="2.8s"
          repeatCount="indefinite"
        />
        <animate
          attributeName="opacity"
          values="1;1;0;0"
          keyTimes="0;0.42;0.43;1"
          dur="2.8s"
          repeatCount="indefinite"
        />
      </circle>
    </svg>
  );
}

function SkillsIcon() {
  return (
    <svg
      viewBox="0 0 40 40"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className="h-6 w-6"
    >
      {/* Three fixed skill blocks */}
      <rect
        x="4"
        y="4"
        width="13"
        height="13"
        rx="2.5"
        fill="#e7e5e4"
        stroke="#1c1917"
        strokeWidth="1.5"
      />
      <rect
        x="23"
        y="4"
        width="13"
        height="13"
        rx="2.5"
        fill="#e7e5e4"
        stroke="#1c1917"
        strokeWidth="1.5"
      />
      <rect
        x="4"
        y="23"
        width="13"
        height="13"
        rx="2.5"
        fill="#e7e5e4"
        stroke="#1c1917"
        strokeWidth="1.5"
      />
      {/* Animated connector lines */}
      <line
        x1="17"
        y1="10.5"
        x2="23"
        y2="10.5"
        stroke="#a8a29e"
        strokeWidth="1"
        strokeDasharray="2 2"
      >
        <animate
          attributeName="stroke-dashoffset"
          from="0"
          to="-4"
          dur="0.7s"
          repeatCount="indefinite"
        />
      </line>
      <line
        x1="10.5"
        y1="17"
        x2="10.5"
        y2="23"
        stroke="#a8a29e"
        strokeWidth="1"
        strokeDasharray="2 2"
      >
        <animate
          attributeName="stroke-dashoffset"
          from="0"
          to="-4"
          dur="0.9s"
          repeatCount="indefinite"
        />
      </line>
      {/* Fourth skill snaps in from below */}
      <rect
        x="23"
        y="23"
        width="13"
        height="13"
        rx="2.5"
        fill="#1c1917"
        stroke="#1c1917"
        strokeWidth="1.5"
      >
        <animate
          attributeName="opacity"
          values="0;0;1;1;0"
          keyTimes="0;0.3;0.5;0.75;1"
          dur="2.5s"
          repeatCount="indefinite"
        />
        <animate
          attributeName="y"
          values="31;31;23;23;31"
          keyTimes="0;0.3;0.5;0.75;1"
          dur="2.5s"
          repeatCount="indefinite"
        />
      </rect>
    </svg>
  );
}

function WebSearchIcon() {
  return (
    <svg
      viewBox="0 0 40 40"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className="h-6 w-6"
    >
      {/* Globe outline */}
      <circle cx="20" cy="20" r="13" stroke="#1c1917" strokeWidth="1.5" />
      {/* Latitude lines */}
      <ellipse
        cx="20"
        cy="20"
        rx="13"
        ry="4.5"
        stroke="#a8a29e"
        strokeWidth="1"
      />
      {/* Meridian */}
      <ellipse
        cx="20"
        cy="20"
        rx="4.5"
        ry="13"
        stroke="#a8a29e"
        strokeWidth="1"
      />
      {/* Equator */}
      <line x1="7" y1="20" x2="33" y2="20" stroke="#a8a29e" strokeWidth="1" />
      {/* Search pulse expanding from center */}
      <circle cx="20" cy="20" r="3.5" fill="#1c1917" />
      <circle
        cx="20"
        cy="20"
        r="3.5"
        fill="none"
        stroke="#1c1917"
        strokeWidth="2"
      >
        <animate
          attributeName="r"
          values="3.5;14;3.5"
          dur="1.8s"
          repeatCount="indefinite"
        />
        <animate
          attributeName="stroke-opacity"
          values="0.8;0;0.8"
          dur="1.8s"
          repeatCount="indefinite"
        />
        <animate
          attributeName="stroke-width"
          values="2;0.5;2"
          dur="1.8s"
          repeatCount="indefinite"
        />
      </circle>
    </svg>
  );
}

function ArtifactsIcon() {
  return (
    <svg
      viewBox="0 0 40 40"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className="h-6 w-6"
    >
      {/* Back document */}
      <rect
        x="9"
        y="14"
        width="18"
        height="22"
        rx="2"
        fill="#e7e5e4"
        stroke="#d6d3d1"
        strokeWidth="1.5"
      />
      {/* Middle document */}
      <rect
        x="12"
        y="10"
        width="18"
        height="22"
        rx="2"
        fill="#f5f5f4"
        stroke="#a8a29e"
        strokeWidth="1.5"
      />
      {/* Front document floats upward */}
      <g>
        <animateTransform
          attributeName="transform"
          type="translate"
          values="0,0;0,-3;0,-3;0,0"
          keyTimes="0;0.3;0.65;1"
          dur="2.5s"
          repeatCount="indefinite"
        />
        <rect
          x="15"
          y="6"
          width="18"
          height="22"
          rx="2"
          fill="white"
          stroke="#1c1917"
          strokeWidth="1.5"
        />
        <line
          x1="19"
          y1="13"
          x2="29"
          y2="13"
          stroke="#e7e5e4"
          strokeWidth="1.5"
        />
        <line
          x1="19"
          y1="17"
          x2="29"
          y2="17"
          stroke="#e7e5e4"
          strokeWidth="1.5"
        />
        <line
          x1="19"
          y1="21"
          x2="25"
          y2="21"
          stroke="#e7e5e4"
          strokeWidth="1.5"
        />
      </g>
    </svg>
  );
}

// ── Section ────────────────────────────────────────────────────────────────────

export function FeaturesSection({ className }: { className?: string }) {
  const features = [
    {
      icon: <AgentOrchestrationIcon />,
      title: "Multi-Agent Orchestration",
      description:
        "A lead agent spawns specialised sub-agents, delegates tasks, collects results, and synthesises a final answer — all in one run.",
    },
    {
      icon: <SandboxIcon />,
      title: "Sandboxed Code Execution",
      description:
        "Python and shell commands run inside an isolated sandbox. No escapes, no surprises — full output streamed back in real time.",
    },
    {
      icon: <MemoryIcon />,
      title: "Persistent Memory",
      description:
        "Agents remember across sessions. Facts, preferences, and context survive so every conversation picks up exactly where the last ended.",
    },
    {
      icon: <SkillsIcon />,
      title: "Composable Skills",
      description:
        "Install and version skills like packages. Each skill is a typed tool with schema — mix built-ins with community or custom tools.",
    },
    {
      icon: <WebSearchIcon />,
      title: "Web Search & Fetch",
      description:
        "First-class live web access via Serper search and Jina AI fetch. Agents browse the web, not a stale training snapshot.",
    },
    {
      icon: <ArtifactsIcon />,
      title: "Artifact Management",
      description:
        "Files, code, reports, and images surface as typed artifacts. Browse, preview, and download them from a dedicated side panel.",
    },
  ];

  return (
    <section
      className={cn("mx-auto w-full max-w-5xl px-6 py-28", className)}
    >
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

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {features.map((f) => (
          <div
            key={f.title}
            className="group flex flex-col gap-4 rounded-2xl border border-stone-200 bg-white p-6 transition-all duration-200 hover:-translate-y-0.5 hover:border-stone-300 hover:shadow-lg hover:shadow-stone-200/70"
          >
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-stone-100">
              {f.icon}
            </div>
            <div className="flex flex-col gap-1.5">
              <h3 className="text-sm font-semibold text-stone-900">
                {f.title}
              </h3>
              <p className="text-sm leading-relaxed text-stone-500">
                {f.description}
              </p>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
