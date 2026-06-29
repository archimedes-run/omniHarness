"use client";

import { RotateCcwIcon, XCircleIcon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/workspace/status-badge";

import { cancelRun, listRuns, retryRun } from "./api";
import type { WorkflowRun } from "./types";

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

const CANCELABLE = new Set(["queued", "running"]);
const RETRYABLE = new Set(["failed", "canceled", "expired"]);

interface RunListProps {
  workflowId: string;
}

export function RunList({ workflowId }: RunListProps) {
  const router = useRouter();

  const [runs, setRuns] = useState<WorkflowRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actioningIds, setActioningIds] = useState<Set<string>>(new Set());

  const loadRuns = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listRuns(workflowId);
      // Sort newest first
      setRuns(
        [...data].sort(
          (a, b) =>
            new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
        ),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load runs");
    } finally {
      setLoading(false);
    }
  }, [workflowId]);

  useEffect(() => {
    void loadRuns();
  }, [loadRuns]);

  const handleCancel = async (run: WorkflowRun) => {
    if (actioningIds.has(run.id)) return;
    setActioningIds((prev) => new Set(prev).add(run.id));
    try {
      const updated = await cancelRun(workflowId, run.id);
      setRuns((prev) => prev.map((r) => (r.id === run.id ? updated : r)));
      toast.success("Run canceled");
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to cancel run";
      if (msg.includes("409") || msg.toLowerCase().includes("already")) {
        toast.error("Run already completed");
      } else {
        toast.error(msg);
      }
    } finally {
      setActioningIds((prev) => {
        const next = new Set(prev);
        next.delete(run.id);
        return next;
      });
    }
  };

  const handleRetry = async (run: WorkflowRun) => {
    if (actioningIds.has(run.id)) return;
    setActioningIds((prev) => new Set(prev).add(run.id));
    try {
      const newRun = await retryRun(workflowId, run.id);
      router.push(`/workspace/workflows/${workflowId}/runs/${newRun.id}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to retry run");
      setActioningIds((prev) => {
        const next = new Set(prev);
        next.delete(run.id);
        return next;
      });
    }
  };

  if (loading) {
    return (
      <div className="text-muted-foreground flex items-center justify-center py-12">
        Loading runs…
      </div>
    );
  }

  if (error) {
    return (
      <div className="border-destructive/50 bg-destructive/10 text-destructive rounded-md border px-4 py-3 text-sm">
        {error}
      </div>
    );
  }

  if (runs.length === 0) {
    return (
      <div className="text-muted-foreground flex flex-col items-center justify-center gap-2 py-12 text-center">
        <p className="text-sm">
          No runs yet. Trigger this workflow to start a run.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col divide-y">
      {runs.map((run) => (
        <div
          key={run.id}
          className="hover:bg-muted/30 flex items-center gap-3 px-1 py-3 transition-colors"
        >
          <Link
            href={`/workspace/workflows/${workflowId}/runs/${run.id}`}
            className="flex min-w-0 flex-1 items-center gap-3"
          >
            <StatusBadge status={run.status} />
            <div className="min-w-0 flex-1">
              <p className="text-muted-foreground text-xs">
                {run.started_at
                  ? `Started ${timeAgo(run.started_at)}`
                  : `Created ${timeAgo(run.created_at)}`}
                {" · "}
                <span className="capitalize">{run.trigger_type}</span>
              </p>
              {run.error_summary ? (
                <p className="text-destructive mt-0.5 truncate text-xs">
                  {run.error_summary}
                </p>
              ) : null}
            </div>
          </Link>

          <div className="flex shrink-0 items-center gap-1">
            {CANCELABLE.has(run.status) ? (
              <Button
                size="sm"
                variant="ghost"
                className="gap-1.5 text-xs"
                disabled={actioningIds.has(run.id)}
                onClick={() => void handleCancel(run)}
              >
                <XCircleIcon className="h-3.5 w-3.5" />
                Cancel
              </Button>
            ) : null}
            {RETRYABLE.has(run.status) ? (
              <Button
                size="sm"
                variant="ghost"
                className="gap-1.5 text-xs"
                disabled={actioningIds.has(run.id)}
                onClick={() => void handleRetry(run)}
              >
                <RotateCcwIcon className="h-3.5 w-3.5" />
                Retry
              </Button>
            ) : null}
          </div>
        </div>
      ))}
    </div>
  );
}
