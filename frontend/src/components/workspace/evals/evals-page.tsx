"use client";

import { CheckCircle2Icon, ChevronRightIcon, CircleXIcon } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  PageCard,
  PageColumn,
  PageHeader,
} from "@/components/workspace/page-kit";
import {
  baselineCell,
  historyPoints,
  isRegression,
  scoreText,
  sortTasks,
  useEval,
  useEvals,
  type EvalSummary,
  type EvalTask,
} from "@/core/evals";
import { formatCost, formatDuration } from "@/core/traces";
import { cn } from "@/lib/utils";

function when(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleString(undefined, {
        year: "numeric",
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
}

/**
 * Score history: one series (pass rate per run of one mode), so no legend;
 * the runs table below is its table view. Its colour is the `chart-series`
 * token (validated for both surfaces with the dataviz palette validator).
 */
export function ScoreChart({
  points,
}: {
  points: ReturnType<typeof historyPoints>;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const W = 640;
  const H = 160;
  const pad = { l: 36, r: 12, t: 12, b: 22 };
  if (points.length === 0) return null;
  const x = (i: number) =>
    points.length === 1
      ? pad.l + (W - pad.l - pad.r) / 2
      : pad.l + (i * (W - pad.l - pad.r)) / (points.length - 1);
  const y = (rate: number) => pad.t + (1 - rate) * (H - pad.t - pad.b);
  const path = points
    .map((p, i) => `${i === 0 ? "M" : "L"}${x(i)},${y(p.rate)}`)
    .join(" ");
  const active = hover !== null ? points[hover] : null;
  return (
    <figure className="relative" data-testid="score-chart">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="h-auto w-full"
        role="img"
        aria-label={`Pass rate over ${points.length} runs, latest ${points.at(-1)!.label}`}
      >
        {[0, 0.5, 1].map((r) => (
          <g key={r}>
            <line
              x1={pad.l}
              x2={W - pad.r}
              y1={y(r)}
              y2={y(r)}
              className="stroke-border"
              strokeWidth={1}
            />
            <text
              x={pad.l - 6}
              y={y(r) + 4}
              textAnchor="end"
              className="fill-muted-foreground text-[11px]"
            >
              {Math.round(r * 100)}%
            </text>
          </g>
        ))}
        <path
          d={path}
          fill="none"
          strokeWidth={2}
          strokeLinejoin="round"
          className="stroke-chart-series"
        />
        {points.map((p, i) => (
          <g key={p.id}>
            <circle
              cx={x(i)}
              cy={y(p.rate)}
              r={hover === i ? 6 : 4}
              strokeWidth={2}
              className="fill-chart-series stroke-card"
            />
            {/* Hit target bigger than the mark. */}
            <circle
              cx={x(i)}
              cy={y(p.rate)}
              r={14}
              fill="transparent"
              tabIndex={0}
              role="button"
              aria-label={`${when(p.at)}: ${p.label}`}
              onMouseEnter={() => setHover(i)}
              onMouseLeave={() => setHover(null)}
              onFocus={() => setHover(i)}
              onBlur={() => setHover(null)}
              className="focus-visible:outline-none"
            />
          </g>
        ))}
      </svg>
      {active && hover !== null && (
        <div
          role="status"
          className="bg-popover text-popover-foreground pointer-events-none absolute rounded-md border px-2 py-1 text-xs shadow-sm"
          style={{
            left: `${(x(hover) / W) * 100}%`,
            top: 0,
            transform: "translateX(-50%)",
          }}
        >
          <span className="font-medium">{active.label}</span> ·{" "}
          {when(active.at)}
        </div>
      )}
    </figure>
  );
}

function PassMark({ pass, label }: { pass: boolean; label?: string }) {
  return pass ? (
    <span className="text-success inline-flex items-center gap-1 font-medium">
      <CheckCircle2Icon className="size-4" aria-hidden="true" />
      {label ?? "Pass"}
    </span>
  ) : (
    <span className="text-destructive inline-flex items-center gap-1 font-medium">
      <CircleXIcon className="size-4" aria-hidden="true" />
      {label ?? "Fail"}
    </span>
  );
}

function TaskRow({ task }: { task: EvalTask }) {
  const [open, setOpen] = useState(false);
  const base = baselineCell(task);
  const regression = isRegression(task);
  const detailId = `eval-task-${task.id}`;
  return (
    <>
      <tr
        className="border-border border-t"
        data-testid="eval-task"
        data-pass={task.pass}
      >
        <td className="py-2 pr-2 align-top">
          <button
            type="button"
            aria-expanded={open}
            aria-controls={detailId}
            onClick={() => setOpen((v) => !v)}
            className="text-foreground focus-visible:ring-ring flex items-start gap-1 rounded text-left focus-visible:ring-2 focus-visible:outline-none"
          >
            <ChevronRightIcon
              className={cn(
                "mt-0.5 size-4 shrink-0 transition-transform",
                open && "rotate-90",
              )}
              aria-hidden="true"
            />
            <span>
              <span className="font-mono text-[13px]">{task.id}</span>{" "}
              <span className="text-foreground-2">{task.title}</span>
            </span>
          </button>
          <div className="mt-1 flex gap-1 pl-5">
            {task.live_only && (
              <span className="border-border text-foreground-2 rounded border px-1.5 py-0.5 text-[11px]">
                live-only
              </span>
            )}
            {regression && (
              <span className="border-destructive/40 bg-destructive/10 text-destructive rounded border px-1.5 py-0.5 text-[11px] font-medium">
                regression
              </span>
            )}
          </div>
        </td>
        <td className="py-2 pr-2 align-top text-sm">
          <PassMark pass={task.pass} />
        </td>
        <td className="text-foreground-2 py-2 pr-2 align-top text-sm">
          {base === "none" ? (
            <span aria-label="no baseline">—</span>
          ) : (
            <PassMark pass={base === "pass"} />
          )}
        </td>
        <td className="text-muted-foreground py-2 text-right align-top text-xs tabular-nums">
          {formatDuration(task.seconds * 1000)}
          <br />
          {formatCost(task.cost_usd)}
        </td>
      </tr>
      {open && (
        <tr id={detailId}>
          <td colSpan={4} className="pb-3 pl-5">
            <ul className="flex flex-col gap-1 text-sm">
              {task.checks.map((check, i) => (
                <li key={i} className="flex items-start gap-2">
                  {check.pass ? (
                    <CheckCircle2Icon
                      className="text-success mt-0.5 size-4 shrink-0"
                      aria-hidden="true"
                    />
                  ) : (
                    <CircleXIcon
                      className="text-destructive mt-0.5 size-4 shrink-0"
                      aria-hidden="true"
                    />
                  )}
                  <span>
                    <span className="sr-only">
                      {check.pass ? "Passed: " : "Failed: "}
                    </span>
                    <span className="text-foreground font-mono text-[13px]">
                      {check.name}
                    </span>
                    {check.reason && (
                      <span className="text-foreground-2">
                        {" "}
                        — {check.reason}
                      </span>
                    )}
                  </span>
                </li>
              ))}
              {task.checks.length === 0 && (
                <li className="text-muted-foreground">No checks recorded.</li>
              )}
            </ul>
            {task.thread_id && (
              <Link
                href={`/workspace/chats/${encodeURIComponent(task.thread_id)}`}
                className="text-primary mt-2 inline-block text-xs underline-offset-2 hover:underline"
              >
                Open the run&apos;s chat
              </Link>
            )}
          </td>
        </tr>
      )}
    </>
  );
}

function RunDetail({ id }: { id: string }) {
  const { result, error, isLoading } = useEval(id);
  if (isLoading)
    return <p className="text-muted-foreground text-sm">Loading the run…</p>;
  if (error)
    return (
      <Alert variant="destructive">
        <AlertTitle>I cannot read this eval run</AlertTitle>
        <AlertDescription>{String(error.message)}</AlertDescription>
      </Alert>
    );
  if (!result) return null;
  return (
    <section
      aria-labelledby="eval-run-heading"
      className="flex flex-col gap-2"
      data-testid="eval-run"
    >
      <h2 id="eval-run-heading" className="text-[15px] font-semibold">
        Tasks of the {result.mode === "real" ? "real-model" : "mock"} run of{" "}
        {when(result.created_at)}:{" "}
        <span className="tabular-nums">{scoreText(result)}</span>
        {result.strict_passed !== null && (
          <span className="text-foreground-2 font-normal">
            {" "}
            (strict {result.strict_passed}/{result.total})
          </span>
        )}
      </h2>
      <PageCard className="overflow-x-auto">
        <table className="w-full text-left">
          <thead>
            <tr className="text-muted-foreground text-xs">
              <th scope="col" className="pb-2 font-medium">
                Task
              </th>
              <th scope="col" className="pb-2 font-medium">
                Result
              </th>
              <th scope="col" className="pb-2 font-medium">
                Baseline
              </th>
              <th scope="col" className="pb-2 text-right font-medium">
                Time · cost
              </th>
            </tr>
          </thead>
          <tbody>
            {sortTasks(result.tasks).map((task) => (
              <TaskRow key={task.id} task={task} />
            ))}
          </tbody>
        </table>
      </PageCard>
    </section>
  );
}

function RunsTable({
  runs,
  selected,
  onSelect,
}: {
  runs: EvalSummary[];
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  return (
    <PageCard className="overflow-x-auto">
      <table className="w-full text-left text-sm" data-testid="eval-runs">
        <caption className="sr-only">Eval runs, newest first</caption>
        <thead>
          <tr className="text-muted-foreground text-xs">
            <th scope="col" className="pb-2 font-medium">
              Date
            </th>
            <th scope="col" className="pb-2 font-medium">
              Mode
            </th>
            <th scope="col" className="pb-2 font-medium">
              Model
            </th>
            <th scope="col" className="pb-2 font-medium">
              Score
            </th>
            <th scope="col" className="pb-2 font-medium">
              Strict
            </th>
            <th scope="col" className="pb-2 font-medium">
              Cost
            </th>
            <th scope="col" className="pb-2 font-medium">
              Regressions
            </th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <tr
              key={run.id}
              className={cn(
                "border-border border-t",
                selected === run.id && "bg-surface-raised",
              )}
              aria-selected={selected === run.id}
            >
              <td className="py-2 pr-2">
                <button
                  type="button"
                  onClick={() => onSelect(run.id)}
                  className="text-primary focus-visible:ring-ring rounded text-left underline-offset-2 hover:underline focus-visible:ring-2 focus-visible:outline-none"
                >
                  {when(run.created_at)}
                </button>
                <div className="text-muted-foreground font-mono text-[11px]">
                  {run.git_sha.slice(0, 8)}
                </div>
              </td>
              <td className="text-foreground-2 py-2 pr-2">
                {run.mode === "real" ? "Real model" : "Mock"}
              </td>
              <td className="text-foreground-2 py-2 pr-2">
                {run.model ?? "—"}
              </td>
              <td className="py-2 pr-2 font-medium tabular-nums">
                {scoreText(run)}
              </td>
              <td className="text-foreground-2 py-2 pr-2 tabular-nums">
                {run.strict_passed === null
                  ? "—"
                  : `${run.strict_passed}/${run.total}`}
              </td>
              <td className="text-foreground-2 py-2 pr-2 tabular-nums">
                {formatCost(run.cost_usd)}
              </td>
              <td className="py-2">
                {run.regressions.length === 0 ? (
                  <span className="text-foreground-2">None</span>
                ) : (
                  <span className="text-destructive font-medium">
                    {run.regressions.join(", ")}
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </PageCard>
  );
}

/** Settings → Evals (spec 009 FR-070 to FR-077). */
export function EvalsPage() {
  const { evals, error, isLoading } = useEvals();
  const runs = useMemo(() => evals?.runs ?? [], [evals]);
  const hasReal = runs.some((r) => r.mode === "real");
  const [mode, setMode] = useState<"real" | "mock" | null>(null);
  const shownMode = mode ?? (hasReal ? "real" : "mock");
  const [selected, setSelected] = useState<string | null>(null);
  const selectedId = selected ?? runs[0]?.id ?? null;
  const points = historyPoints(runs, shownMode);
  return (
    <PageColumn width="wide">
      <PageHeader
        title="Evals"
        description="How the assistant scores on tasks from your own use. Each task passes only when every automatic check passes."
      />
      {isLoading && (
        <p className="text-muted-foreground text-sm">Loading eval results…</p>
      )}
      {error && (
        <Alert variant="destructive">
          <AlertTitle>I cannot read the eval results</AlertTitle>
          <AlertDescription>{String(error.message)}</AlertDescription>
        </Alert>
      )}
      {evals && runs.length === 0 && (
        <PageCard data-testid="evals-empty">
          <p className="text-foreground text-sm font-medium">
            No eval runs yet
          </p>
          <p className="text-foreground-2 mt-1 text-sm">
            Run{" "}
            <code className="bg-surface-raised rounded px-1">make eval</code> to
            record a score. Results are read from{" "}
            <code className="bg-surface-raised rounded px-1 break-all">
              {evals.results_dir}
            </code>
            .
          </p>
        </PageCard>
      )}
      {evals?.baseline && (
        <p className="text-foreground-2 text-sm" data-testid="eval-baseline">
          Baseline:{" "}
          <span className="text-foreground font-medium tabular-nums">
            {scoreText(evals.baseline)}
          </span>
          {evals.baseline.strict_passed !== null &&
            ` (strict ${evals.baseline.strict_passed}/${evals.baseline.total})`}
          {evals.baseline.model && `, ${evals.baseline.model}`}, recorded{" "}
          {when(evals.baseline.created_at)}
        </p>
      )}
      {runs.length > 0 && (
        <>
          <section
            aria-labelledby="score-history"
            className="flex flex-col gap-2"
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 id="score-history" className="text-[15px] font-semibold">
                Score history
              </h2>
              <div
                role="group"
                aria-label="Mode"
                className="bg-surface-raised flex rounded-lg p-0.5 text-sm"
              >
                {(["real", "mock"] as const).map((m) => (
                  <button
                    key={m}
                    type="button"
                    aria-pressed={shownMode === m}
                    onClick={() => setMode(m)}
                    className={cn(
                      "focus-visible:ring-ring rounded-md px-3 py-1 focus-visible:ring-2 focus-visible:outline-none",
                      shownMode === m
                        ? "bg-card text-foreground font-medium shadow-sm"
                        : "text-foreground-2 hover:text-foreground",
                    )}
                  >
                    {m === "real" ? "Real model" : "Mock"}
                  </button>
                ))}
              </div>
            </div>
            <PageCard>
              {points.length > 0 ? (
                <ScoreChart points={points} />
              ) : (
                <p className="text-muted-foreground text-sm">
                  No {shownMode === "real" ? "real-model" : "mock"} runs yet.
                </p>
              )}
            </PageCard>
          </section>
          <section
            aria-labelledby="eval-runs-heading"
            className="flex flex-col gap-2"
          >
            <h2 id="eval-runs-heading" className="text-[15px] font-semibold">
              Runs
            </h2>
            <RunsTable
              runs={runs}
              selected={selectedId}
              onSelect={setSelected}
            />
          </section>
          {selectedId && <RunDetail id={selectedId} />}
        </>
      )}
    </PageColumn>
  );
}
