"use client";

import { useQueryClient } from "@tanstack/react-query";
import {
  AppWindowIcon,
  CheckIcon,
  ChevronRightIcon,
  CircleAlertIcon,
  CircleDotIcon,
  FileCode2Icon,
  Loader2Icon,
  MessageSquareTextIcon,
  SquareIcon,
  SquareTerminalIcon,
  WrenchIcon,
  XIcon,
} from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  type CodeJob,
  CodeJobNotFound,
  type CodeJobStatus,
  type CodeJobStep,
} from "@/core/code-jobs/api";
import { useCodeJob, useStopCodeJob } from "@/core/code-jobs/hooks";
import { safeField, safeLines } from "@/core/display/safe";
import { cn } from "@/lib/utils";

import { useArtifacts } from "../artifacts";
import { useNow } from "../home/use-now";

/**
 * A coding job (spec 009, Slice 1): OpenCode working in this chat's container
 * sandbox. Live steps from the job's event stream (commands with their exit
 * codes, file writes), cost against its budget, Stop, and, when it ends, the
 * status the SYSTEM decided from evidence (the verification command's exit
 * code, the expected files, the files changed). The worker's own words are
 * shown as its words, never as the result.
 */

const STATUS: Record<
  CodeJobStatus,
  { label: string; className: string; describe: string }
> = {
  running: {
    label: "Running",
    className: "bg-primary-subtle text-foreground",
    describe: "The worker is running in the sandbox.",
  },
  verified: {
    label: "Verified",
    className: "bg-success text-success-foreground",
    describe:
      "Checked by the system: the build exited 0 and the expected files exist.",
  },
  unverified: {
    label: "Unverified",
    className: "bg-warning text-warning-foreground",
    describe:
      "Nothing was built or tested by the system, so the result is not verified.",
  },
  failed: {
    label: "Failed",
    className: "bg-destructive text-destructive-foreground",
    describe: "The system's check failed.",
  },
  stopped: {
    label: "Stopped",
    className:
      "bg-secondary text-secondary-foreground border-border-strong border",
    describe: "The job was stopped.",
  },
  blocked: {
    label: "Blocked",
    className: "bg-warning text-warning-foreground",
    describe: "The job could not finish.",
  },
};

function formatDuration(seconds: number) {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  return `${m}m ${String(s % 60).padStart(2, "0")}s`;
}

function money(n: number | undefined | null) {
  const v = Number(n ?? 0);
  return `$${v < 0.01 && v > 0 ? v.toFixed(3) : v.toFixed(2)}`;
}

function lastActivity(steps: CodeJobStep[]): string {
  for (let i = steps.length - 1; i >= 0; i--) {
    const step = steps[i]!;
    if (step.kind === "command") {
      return step.exit_code === null
        ? `Ran ${step.command}`
        : `Ran ${step.command} (exit ${step.exit_code})`;
    }
    if (step.kind === "file") return `${capitalise(step.action)} ${step.path}`;
    if (step.kind === "phase") return step.text;
    if (step.kind === "verify") return `Checking: ${step.command}`;
  }
  return "Starting the worker in the sandbox…";
}

function capitalise(s: string) {
  return s ? s[0]!.toUpperCase() + s.slice(1) : s;
}

export function CodeJobCard({
  threadId,
  toolCallId,
  title,
  resultText,
}: {
  threadId: string;
  toolCallId: string;
  title?: string;
  /** The tool's result, once it returned (the lead's copy of the report). */
  resultText?: string;
}) {
  // Until the tool returns, the job may not exist yet (or the chat may have
  // reconnected mid-run): keep looking for it, whatever the stream says.
  const waiting = resultText === undefined;
  const query = useCodeJob({ threadId, toolCallId, waiting });
  const job = query.data?.job;
  const steps = query.data?.steps ?? [];

  if (!job) {
    const notStarted = query.error instanceof CodeJobNotFound;
    return (
      <section
        aria-label="Coding job"
        className="bg-card text-card-foreground w-full rounded-lg border p-3"
        data-testid="code-job-card"
      >
        <div className="flex items-center gap-2 text-sm">
          <SquareTerminalIcon
            className="text-muted-foreground size-4"
            aria-hidden
          />
          <span className="font-medium">Coding job</span>
          {title ? (
            <span className="text-muted-foreground truncate">
              {safeField(title)}
            </span>
          ) : null}
        </div>
        <p className="text-muted-foreground mt-2 text-sm" role="status">
          {resultText !== undefined
            ? safeField(resultText).slice(0, 400)
            : notStarted || query.isLoading
              ? "Starting the worker in the sandbox…"
              : "The job's progress could not be loaded."}
        </p>
      </section>
    );
  }
  return (
    <JobView
      threadId={threadId}
      toolCallId={toolCallId}
      job={job}
      steps={steps}
      month={query.data?.month}
    />
  );
}

function JobView({
  threadId,
  toolCallId,
  job,
  steps,
  month,
}: {
  threadId: string;
  toolCallId: string;
  job: CodeJob;
  steps: CodeJobStep[];
  month?: { spent_usd: number; cap_usd: number | null };
}) {
  const running = job.status === "running";
  const status = STATUS[job.status] ?? STATUS.blocked;
  const now = useNow(running ? 1000 : 60_000);
  const started = new Date(job.created_at).getTime();
  const ended = job.finished_at
    ? new Date(job.finished_at).getTime()
    : now.getTime();
  const elapsed = (ended - started) / 1000;
  const stop = useStopCodeJob({ threadId, toolCallId });
  const { select, setOpen } = useArtifacts();
  const queryClient = useQueryClient();
  const stepsId = useId();

  // The steps are open while the job runs and fold away when it ends; the
  // person can open them again (spec 009 FR-041).
  const [open, setOpenSteps] = useState(running);
  const wasRunning = useRef(running);
  useEffect(() => {
    if (wasRunning.current && !running) {
      setOpenSteps(false);
      // A published build is a new artifact: refresh the panel's list.
      void queryClient.invalidateQueries({
        queryKey: ["artifact-manifests", threadId],
      });
    }
    wasRunning.current = running;
  }, [running, queryClient, threadId]);

  const result = job.result;
  const published = result?.published;
  const visibleSteps = useMemo(
    () => steps.filter((s) => s.kind !== "phase" || s.phase !== "working"),
    [steps],
  );
  const activity = running ? lastActivity(steps) : null;

  return (
    <section
      aria-label={`Coding job: ${safeField(job.title)}`}
      className="bg-card text-card-foreground w-full rounded-lg border"
      data-testid="code-job-card"
      data-status={job.status}
    >
      <header className="flex flex-wrap items-start gap-x-3 gap-y-2 p-3">
        <SquareTerminalIcon
          className="text-muted-foreground mt-0.5 size-4 shrink-0"
          aria-hidden
        />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-medium [overflow-wrap:anywhere]">
              {safeField(job.title)}
            </h3>
            <span
              className={cn(
                "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium",
                status.className,
              )}
              data-testid="code-job-status"
              title={status.describe}
            >
              {running ? (
                <Loader2Icon className="size-3 animate-spin" aria-hidden />
              ) : null}
              {status.label}
            </span>
          </div>
          <p className="text-muted-foreground mt-1 text-xs">
            <span>{safeField(job.project_dir)}</span>
            <span aria-hidden> · </span>
            <span>{formatDuration(elapsed)}</span>
            <span aria-hidden> · </span>
            <span data-testid="code-job-cost">
              {money(job.spent_usd)} of {money(job.budget_usd)}
            </span>
            <span aria-hidden> · </span>
            <span>
              {job.calls} model call{job.calls === 1 ? "" : "s"}
            </span>
            {month?.cap_usd ? (
              <>
                <span aria-hidden> · </span>
                <span>
                  {money(month.spent_usd)} this month of {money(month.cap_usd)}
                </span>
              </>
            ) : null}
          </p>
        </div>
        {running ? (
          <Button
            variant="outline"
            size="sm"
            onClick={() => stop.mutate(job.id)}
            disabled={stop.isPending || job.stop_requested}
            aria-label="Stop coding job"
            data-testid="code-job-stop"
          >
            <SquareIcon className="size-3.5" aria-hidden />
            {job.stop_requested || stop.isPending ? "Stopping…" : "Stop"}
          </Button>
        ) : null}
      </header>

      {running ? (
        <p
          className="text-foreground-2 border-t px-3 py-2 text-sm [overflow-wrap:anywhere]"
          role="status"
          aria-live="polite"
          data-testid="code-job-activity"
        >
          {safeField(activity ?? "")}
        </p>
      ) : (
        <Evidence job={job} />
      )}

      {!running && published ? (
        <div className="border-t px-3 py-2">
          <Button
            size="sm"
            onClick={() => {
              // The built index.html itself: the panel opens it in preview.
              select(published.path);
              setOpen(true);
            }}
            data-testid="code-job-open-app"
          >
            <AppWindowIcon className="size-3.5" aria-hidden />
            Open the app
          </Button>
        </div>
      ) : null}

      <div className="border-t">
        <button
          type="button"
          className="text-muted-foreground hover:text-foreground focus-visible:ring-ring/50 flex w-full items-center gap-2 px-3 py-2 text-left text-xs outline-none focus-visible:ring-[3px]"
          aria-expanded={open}
          aria-controls={stepsId}
          onClick={() => setOpenSteps((v) => !v)}
          data-testid="code-job-steps-toggle"
        >
          <ChevronRightIcon
            className={cn("size-3.5 transition-transform", open && "rotate-90")}
            aria-hidden
          />
          {visibleSteps.length} step{visibleSteps.length === 1 ? "" : "s"}
          {!running ? ` · ${formatDuration(elapsed)}` : ""}
        </button>
        {open ? (
          <ol
            id={stepsId}
            className="flex max-h-96 flex-col gap-1 overflow-y-auto px-3 pb-3"
            data-testid="code-job-steps"
          >
            {visibleSteps.map((step) => (
              <StepRow key={step.seq} step={step} />
            ))}
          </ol>
        ) : null}
      </div>
    </section>
  );
}

function Evidence({ job }: { job: CodeJob }) {
  const r = job.result;
  const verify = r?.verify;
  const changed = r?.files_changed;
  const tests = r?.worker?.tests ?? [];
  const names = [...(changed?.added ?? []), ...(changed?.modified ?? [])];
  return (
    <div className="border-t px-3 py-2 text-sm" data-testid="code-job-evidence">
      {job.reason ? (
        <p className="text-foreground-2 mb-1 [overflow-wrap:anywhere]">
          {safeField(job.reason)}
        </p>
      ) : null}
      <ul className="flex flex-col gap-1">
        <li className="flex items-start gap-2">
          <Mark
            ok={verify ? verify.exit_code === 0 && !verify.timed_out : null}
          />
          <span className="[overflow-wrap:anywhere]">
            {verify ? (
              <>
                Build check{" "}
                <code className="text-xs">{safeField(verify.command)}</code>{" "}
                {verify.timed_out
                  ? "did not finish"
                  : `exited ${verify.exit_code ?? "?"}`}{" "}
                <span className="text-muted-foreground">
                  (run by the system)
                </span>
              </>
            ) : (
              "No build check was run"
            )}
          </span>
        </li>
        {(r?.expected_files ?? []).map((f) => (
          <li key={f.path} className="flex items-start gap-2">
            <Mark ok={f.exists} />
            <span className="[overflow-wrap:anywhere]">
              <code className="text-xs">{safeField(f.path)}</code>{" "}
              {f.exists ? `exists (${f.bytes} bytes)` : "is missing"}
            </span>
          </li>
        ))}
        <li className="flex items-start gap-2">
          <Mark ok={null} />
          <span className="[overflow-wrap:anywhere]">
            {changed?.count ?? 0} file{changed?.count === 1 ? "" : "s"} changed
            {names.length ? (
              <span className="text-muted-foreground">
                {": "}
                {names.slice(0, 6).map(safeField).join(", ")}
                {names.length > 6 ? `, and ${names.length - 6} more` : ""}
              </span>
            ) : null}
          </span>
        </li>
        <li className="flex items-start gap-2">
          <Mark
            ok={tests.length ? tests.every((t) => t.exit_code === 0) : null}
          />
          <span className="[overflow-wrap:anywhere]">
            {tests.length
              ? tests
                  .slice(-3)
                  .map(
                    (t) =>
                      `${safeField(t.command)}: exit ${t.exit_code ?? "?"}`,
                  )
                  .join("; ")
              : "No tests were run"}
          </span>
        </li>
      </ul>
    </div>
  );
}

function Mark({ ok }: { ok: boolean | null }) {
  if (ok === true) {
    return (
      <CheckIcon
        className="text-success mt-0.5 size-4 shrink-0"
        aria-label="passed"
      />
    );
  }
  if (ok === false) {
    return (
      <XIcon
        className="text-destructive mt-0.5 size-4 shrink-0"
        aria-label="failed"
      />
    );
  }
  return (
    <CircleDotIcon
      className="text-muted-foreground mt-0.5 size-4 shrink-0"
      aria-label="information"
    />
  );
}

function StepRow({ step }: { step: CodeJobStep }) {
  const [expanded, setExpanded] = useState(false);
  if (step.kind === "command" || step.kind === "verify") {
    const failed =
      step.kind === "verify"
        ? step.timed_out || step.exit_code !== 0
        : step.exit_code !== null && step.exit_code !== 0;
    const exit =
      step.kind === "verify" && step.timed_out
        ? "timed out"
        : step.exit_code === null
          ? "no exit code"
          : `exit ${step.exit_code}`;
    return (
      <li className="text-xs" data-testid="code-job-step-command">
        <button
          type="button"
          className="hover:bg-surface-raised focus-visible:ring-ring/50 flex w-full items-start gap-2 rounded px-1 py-0.5 text-left outline-none focus-visible:ring-[3px]"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
        >
          <SquareTerminalIcon
            className="text-muted-foreground mt-0.5 size-3.5 shrink-0"
            aria-hidden
          />
          <code className="min-w-0 flex-1 [overflow-wrap:anywhere]">
            {step.kind === "verify" ? "check: " : ""}
            {safeField(step.command)}
          </code>
          <span
            className={cn(
              "shrink-0 font-medium",
              failed ? "text-destructive" : "text-success",
              step.exit_code === null &&
                step.kind === "command" &&
                "text-muted-foreground",
            )}
          >
            {exit}
          </span>
        </button>
        {expanded && step.output ? (
          <pre className="bg-muted text-foreground-2 mt-1 max-h-48 overflow-auto rounded p-2 text-[11px] whitespace-pre-wrap">
            {safeLines(step.output)}
          </pre>
        ) : null}
      </li>
    );
  }
  if (step.kind === "file") {
    return (
      <li className="flex items-start gap-2 px-1 text-xs">
        <FileCode2Icon
          className="text-muted-foreground mt-0.5 size-3.5 shrink-0"
          aria-hidden
        />
        <span className="[overflow-wrap:anywhere]">
          {capitalise(step.action)} <code>{safeField(step.path)}</code>
          {step.status !== "ok" ? (
            <span className="text-destructive"> (failed)</span>
          ) : null}
        </span>
      </li>
    );
  }
  if (step.kind === "tool") {
    return (
      <li className="text-muted-foreground flex items-start gap-2 px-1 text-xs">
        <WrenchIcon className="mt-0.5 size-3.5 shrink-0" aria-hidden />
        <span className="[overflow-wrap:anywhere]">
          {safeField(step.tool)} {safeField(step.title)}
        </span>
      </li>
    );
  }
  if (step.kind === "message") {
    return (
      <li className="text-foreground-2 flex items-start gap-2 px-1 text-xs">
        <MessageSquareTextIcon
          className="text-muted-foreground mt-0.5 size-3.5 shrink-0"
          aria-hidden
        />
        <span className="[overflow-wrap:anywhere]">
          <span className="text-muted-foreground">
            Worker says (not verified):{" "}
          </span>
          {safeField(step.text).slice(0, 600)}
        </span>
      </li>
    );
  }
  if (step.kind === "error") {
    return (
      <li className="text-destructive flex items-start gap-2 px-1 text-xs">
        <CircleAlertIcon className="mt-0.5 size-3.5 shrink-0" aria-hidden />
        <span className="[overflow-wrap:anywhere]">
          {safeField(step.message)}
        </span>
      </li>
    );
  }
  if (step.kind === "check") {
    return (
      <li className="flex items-start gap-2 px-1 text-xs">
        <Mark ok={step.exists} />
        <span className="[overflow-wrap:anywhere]">
          check: <code>{safeField(step.path)}</code>{" "}
          {step.exists ? `exists (${step.bytes} bytes)` : "is missing"}
        </span>
      </li>
    );
  }
  if (step.kind === "published") {
    return (
      <li className="flex items-start gap-2 px-1 text-xs">
        <AppWindowIcon
          className="text-muted-foreground mt-0.5 size-3.5 shrink-0"
          aria-hidden
        />
        <span>Published to the artifact panel</span>
      </li>
    );
  }
  return (
    <li className="text-muted-foreground px-1 text-xs">
      {safeField(step.text)}
    </li>
  );
}
