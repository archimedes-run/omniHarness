"use client";

import {
  AlertCircleIcon,
  ArrowLeftIcon,
  CheckCircleIcon,
  ClockIcon,
  ExternalLinkIcon,
  Loader2Icon,
  RotateCcwIcon,
  XCircleIcon,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/workspace/status-badge";

import { cancelRun, getRun, getWorkflow, retryRun } from "./api";
import type { Workflow, WorkflowRun } from "./types";
import { WorkflowMessages } from "./workflow-messages";

const TERMINAL = new Set(["succeeded", "failed", "canceled", "expired"]);
const CANCELABLE = new Set(["queued", "running"]);
const RETRYABLE = new Set(["failed", "canceled", "expired"]);

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  if (diff < 60000) return "just now";
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
  return new Date(iso).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
}

function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function StatusIcon({ status }: { status: string }) {
  if (status === "succeeded")
    return <CheckCircleIcon className="h-4 w-4 text-green-500" />;
  if (status === "failed")
    return <AlertCircleIcon className="text-destructive h-4 w-4" />;
  if (status === "canceled" || status === "expired")
    return <XCircleIcon className="text-muted-foreground h-4 w-4" />;
  if (status === "running" || status === "queued")
    return <Loader2Icon className="h-4 w-4 animate-spin text-blue-500" />;
  return <ClockIcon className="text-muted-foreground h-4 w-4" />;
}

interface RunTimelineProps {
  workflowId: string;
  runId: string;
}

export function RunTimeline({ workflowId, runId }: RunTimelineProps) {
  const router = useRouter();

  const [workflow, setWorkflow] = useState<Workflow | null>(null);
  const [run, setRun] = useState<WorkflowRun | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actioning, setActioning] = useState(false);

  // Initial load
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    Promise.all([getWorkflow(workflowId), getRun(workflowId, runId)])
      .then(([wf, r]) => {
        if (!cancelled) {
          setWorkflow(wf);
          setRun(r);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load run");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [workflowId, runId]);

  // Polling while active
  useEffect(() => {
    if (!run || TERMINAL.has(run.status)) return;

    const intervalId = setInterval(() => {
      getRun(workflowId, runId)
        .then((updated) => {
          setRun(updated);
          if (TERMINAL.has(updated.status)) {
            clearInterval(intervalId);
          }
        })
        .catch(() => {
          /* ignore transient errors during polling */
        });
    }, 3000);

    return () => clearInterval(intervalId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run?.status, workflowId, runId]);

  const handleCancel = async () => {
    if (!run || actioning) return;
    setActioning(true);
    try {
      const updated = await cancelRun(workflowId, run.id);
      setRun(updated);
      toast.success("Run canceled");
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to cancel run";
      if (msg.includes("409") || msg.toLowerCase().includes("already")) {
        toast.error("Run already completed");
      } else {
        toast.error(msg);
      }
    } finally {
      setActioning(false);
    }
  };

  const handleRetry = async () => {
    if (!run || actioning) return;
    setActioning(true);
    try {
      const newRun = await retryRun(workflowId, run.id);
      router.push(`/workspace/workflows/${workflowId}/runs/${newRun.id}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to retry run");
      setActioning(false);
    }
  };

  if (loading) {
    return (
      <div className="flex flex-1 items-center justify-center p-6">
        <Loader2Icon className="text-muted-foreground h-6 w-6 animate-spin" />
      </div>
    );
  }

  if (error || !run || !workflow) {
    return (
      <div className="flex flex-1 flex-col gap-4 p-6">
        <Link
          href={`/workspace/workflows/${workflowId}`}
          className="text-muted-foreground hover:text-foreground flex items-center gap-1.5 text-sm"
        >
          <ArrowLeftIcon className="h-4 w-4" />
          Back to workflow
        </Link>
        <div className="border-destructive/50 bg-destructive/10 text-destructive rounded-md border px-4 py-3 text-sm">
          {error ?? "Run not found"}
        </div>
      </div>
    );
  }

  const spec = workflow.spec_json;

  return (
    <div className="flex flex-1 flex-col gap-6 p-6">
      {/* Back navigation */}
      <Link
        href={`/workspace/workflows/${workflowId}`}
        className="text-muted-foreground hover:text-foreground flex items-center gap-1.5 text-sm"
      >
        <ArrowLeftIcon className="h-4 w-4" />
        {workflow.title}
      </Link>

      {/* Header */}
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2">
            <StatusIcon status={run.status} />
            <h1 className="text-xl font-semibold">Run</h1>
            <StatusBadge status={run.status} />
          </div>

          <div className="ml-auto flex items-center gap-2">
            {CANCELABLE.has(run.status) ? (
              <Button
                size="sm"
                variant="outline"
                disabled={actioning}
                onClick={() => void handleCancel()}
              >
                <XCircleIcon className="mr-1.5 h-3.5 w-3.5" />
                Cancel
              </Button>
            ) : null}
            {RETRYABLE.has(run.status) ? (
              <Button
                size="sm"
                variant="outline"
                disabled={actioning}
                onClick={() => void handleRetry()}
              >
                <RotateCcwIcon className="mr-1.5 h-3.5 w-3.5" />
                Retry
              </Button>
            ) : null}
          </div>
        </div>

        {/* Meta info */}
        <div className="text-muted-foreground flex flex-wrap gap-4 text-xs">
          {run.started_at ? (
            <span>
              <ClockIcon className="mr-1 inline h-3 w-3" />
              Started {formatDateTime(run.started_at)} (
              {timeAgo(run.started_at)})
            </span>
          ) : null}
          {run.completed_at ? (
            <span>Completed {formatDateTime(run.completed_at)}</span>
          ) : null}
          <span className="capitalize">Trigger: {run.trigger_type}</span>
          {run.source_run_id ? (
            <span>
              Retry of{" "}
              <Link
                href={`/workspace/workflows/${workflowId}/runs/${run.source_run_id}`}
                className="text-foreground underline underline-offset-2"
              >
                previous run
              </Link>
            </span>
          ) : null}
        </div>

        {/* Error summary */}
        {run.error_summary ? (
          <div className="border-destructive/50 bg-destructive/10 text-destructive rounded-md border px-4 py-3 text-sm">
            <AlertCircleIcon className="mr-1.5 inline h-4 w-4" />
            {run.error_summary}
          </div>
        ) : null}

        {/* Link to underlying thread */}
        {run.thread_id ? (
          <div>
            <Link
              href={`/workspace/chats/${run.thread_id}`}
              className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1.5 text-xs underline underline-offset-2"
            >
              <ExternalLinkIcon className="h-3 w-3" />
              View in chat
            </Link>
          </div>
        ) : null}
      </div>

      {/* Plan section */}
      {spec ? (
        <div className="rounded-lg border p-4">
          <h2 className="mb-3 text-sm font-semibold">Plan</h2>
          {spec.description ? (
            <p className="text-muted-foreground mb-3 text-sm">
              {spec.description}
            </p>
          ) : null}

          <ol className="flex flex-col gap-3">
            {spec.steps.map((step, idx) => (
              <li key={idx} className="flex gap-3">
                <span className="bg-muted text-muted-foreground mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-xs font-medium">
                  {idx + 1}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium">{step.title}</p>
                  {step.description ? (
                    <p className="text-muted-foreground mt-0.5 text-xs">
                      {step.description}
                    </p>
                  ) : null}
                  {step.suggested_tools.length > 0 ? (
                    <div className="mt-1 flex flex-wrap gap-1">
                      {step.suggested_tools.map((tool) => (
                        <span
                          key={tool}
                          className="bg-muted text-muted-foreground rounded px-1.5 py-0.5 font-mono text-xs"
                        >
                          {tool}
                        </span>
                      ))}
                    </div>
                  ) : null}
                </div>
              </li>
            ))}
          </ol>

          {spec.risks.length > 0 ? (
            <div className="mt-4">
              <p className="mb-1 text-xs font-medium">Risks</p>
              <ul className="text-muted-foreground list-disc pl-4 text-xs">
                {spec.risks.map((risk, i) => (
                  <li key={i}>{risk}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : null}

      {/* Final summary */}
      {run.status === "succeeded" && run.final_summary ? (
        <div className="rounded-lg border border-green-200 bg-green-50 p-4 dark:border-green-900 dark:bg-green-950/30">
          <h2 className="mb-2 text-sm font-semibold text-green-800 dark:text-green-300">
            Summary
          </h2>
          <p className="text-sm whitespace-pre-wrap text-green-900 dark:text-green-200">
            {run.final_summary}
          </p>
        </div>
      ) : null}

      {/* Messages / execution trace */}
      {run.thread_id && run.run_id ? (
        <div className="flex flex-col gap-3">
          <h2 className="text-sm font-semibold">Execution trace</h2>
          <WorkflowMessages threadId={run.thread_id} runId={run.run_id} />
        </div>
      ) : run.status === "queued" ? (
        <div className="text-muted-foreground flex items-center gap-2 py-4 text-sm">
          <Loader2Icon className="h-4 w-4 animate-spin" />
          Waiting to start…
        </div>
      ) : run.status === "running" ? (
        <div className="text-muted-foreground flex items-center gap-2 py-4 text-sm">
          <Loader2Icon className="h-4 w-4 animate-spin" />
          Running…
        </div>
      ) : null}
    </div>
  );
}
