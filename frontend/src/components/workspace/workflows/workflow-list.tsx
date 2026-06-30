"use client";

import { GitBranchIcon, Loader2Icon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

import {
  createWorkflow,
  getTemplates,
  listRuns,
  listWorkflows,
  triggerRun,
} from "./api";
import { CreateWorkflowModal } from "./create-workflow-modal";
import type { Workflow, WorkflowRun, WorkflowTemplate } from "./types";
import { WorkflowCard } from "./workflow-card";

type TabValue = "all" | "draft" | "active" | "archived";

const TABS: { label: string; value: TabValue }[] = [
  { label: "All", value: "all" },
  { label: "Drafts", value: "draft" },
  { label: "Active", value: "active" },
  { label: "Archived", value: "archived" },
];

export function WorkflowList() {
  const router = useRouter();

  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [templates, setTemplates] = useState<WorkflowTemplate[]>([]);
  const [lastRuns, setLastRuns] = useState<Record<string, WorkflowRun | null>>(
    {},
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<TabValue>("all");
  const [showCreate, setShowCreate] = useState(false);
  const [runningIds, setRunningIds] = useState<Set<string>>(new Set());
  const [usingTemplate, setUsingTemplate] = useState<string | null>(null);
  const [pendingRun, setPendingRun] = useState<Workflow | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [wfs, tpls] = await Promise.all([listWorkflows(), getTemplates()]);
      setWorkflows(wfs);
      setTemplates(tpls);

      // Fetch most recent run for each workflow
      const runEntries = await Promise.all(
        wfs.map(async (wf) => {
          try {
            const runs = await listRuns(wf.id);
            // runs come newest-first from the backend
            return [wf.id, runs[0] ?? null] as const;
          } catch {
            return [wf.id, null] as const;
          }
        }),
      );
      setLastRuns(Object.fromEntries(runEntries));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load workflows");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const handleRun = async (wf: Workflow) => {
    if (runningIds.has(wf.id)) return;
    if (wf.approval_policy === "approval_required") {
      setPendingRun(wf);
      return;
    }
    setRunningIds((prev) => new Set(prev).add(wf.id));
    try {
      const run = await triggerRun(wf.id);
      router.push(`/workspace/workflows/${wf.id}/runs/${run.id}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to trigger run");
      setRunningIds((prev) => {
        const next = new Set(prev);
        next.delete(wf.id);
        return next;
      });
    }
  };

  const handleConfirmedRun = async (wf: Workflow) => {
    setRunningIds((prev) => new Set(prev).add(wf.id));
    try {
      const run = await triggerRun(wf.id, { confirmed: true });
      router.push(`/workspace/workflows/${wf.id}/runs/${run.id}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to trigger run");
      setRunningIds((prev) => {
        const next = new Set(prev);
        next.delete(wf.id);
        return next;
      });
    }
  };

  const handleUseTemplate = async (template: WorkflowTemplate) => {
    setUsingTemplate(template.id);
    try {
      const wf = await createWorkflow({
        title: template.title,
        description: template.description,
        instruction_prompt: template.instruction_prompt,
        approval_policy: template.approval_policy,
        spec_json: template.spec_json,
      });
      router.push(`/workspace/workflows/${wf.id}`);
    } catch (err) {
      toast.error(
        err instanceof Error
          ? err.message
          : "Failed to create workflow from template",
      );
      setUsingTemplate(null);
    }
  };

  const filtered = workflows.filter((wf) => {
    if (activeTab === "all") return true;
    return wf.status === activeTab;
  });

  return (
    <div className="flex flex-1 flex-col gap-6 p-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <GitBranchIcon className="h-6 w-6" />
          <h1 className="text-2xl font-semibold">Workflows</h1>
        </div>
        <Button onClick={() => setShowCreate(true)}>New workflow</Button>
      </div>

      {/* Templates section */}
      {templates.length > 0 && (
        <div className="flex flex-col gap-3">
          <h2 className="text-muted-foreground text-sm font-semibold">
            Start from a template
          </h2>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {templates.map((tpl) => (
              <div
                key={tpl.id}
                className="bg-muted/20 flex flex-col gap-2 rounded-lg border p-4"
              >
                <div className="flex items-start justify-between gap-2">
                  <p className="text-sm font-medium">{tpl.title}</p>
                  <span className="bg-muted text-muted-foreground shrink-0 rounded px-1.5 py-0.5 text-xs">
                    Template
                  </span>
                </div>
                {tpl.description && (
                  <p className="text-muted-foreground line-clamp-2 text-xs">
                    {tpl.description}
                  </p>
                )}
                <Button
                  size="sm"
                  variant="outline"
                  className="mt-auto w-full"
                  disabled={usingTemplate === tpl.id}
                  onClick={() => void handleUseTemplate(tpl)}
                >
                  {usingTemplate === tpl.id ? (
                    <Loader2Icon className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                  ) : null}
                  Use template
                </Button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1 border-b">
        {TABS.map((tab) => (
          <button
            key={tab.value}
            onClick={() => setActiveTab(tab.value)}
            className={[
              "px-3 py-2 text-sm font-medium transition-colors",
              activeTab === tab.value
                ? "border-foreground text-foreground border-b-2"
                : "text-muted-foreground hover:text-foreground",
            ].join(" ")}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Error */}
      {error ? (
        <div className="border-destructive/50 bg-destructive/10 text-destructive rounded-md border px-4 py-3 text-sm">
          {error}
        </div>
      ) : null}

      {/* Content */}
      {loading ? (
        <div className="text-muted-foreground flex flex-1 items-center justify-center">
          Loading…
        </div>
      ) : filtered.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 text-center">
          <GitBranchIcon className="text-muted-foreground/40 h-12 w-12" />
          <div>
            <p className="text-base font-medium">
              {activeTab === "all"
                ? "No workflows yet"
                : `No ${activeTab} workflows`}
            </p>
            <p className="text-muted-foreground mt-1 text-sm">
              {activeTab === "all"
                ? "Create your first workflow to get started."
                : "Try a different filter."}
            </p>
          </div>
          {activeTab === "all" ? (
            <Button onClick={() => setShowCreate(true)}>New workflow</Button>
          ) : null}
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {filtered.map((wf) => (
            <WorkflowCard
              key={wf.id}
              workflow={wf}
              lastRun={lastRuns[wf.id]}
              onRun={() => void handleRun(wf)}
            />
          ))}
        </div>
      )}

      {/* Approval confirmation dialog */}
      <Dialog
        open={pendingRun !== null}
        onOpenChange={(v) => !v && setPendingRun(null)}
      >
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>Run workflow?</DialogTitle>
          </DialogHeader>
          <p className="text-muted-foreground text-sm">
            &quot;{pendingRun?.title}&quot; may take irreversible or external
            actions. Run anyway?
          </p>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setPendingRun(null)}
              disabled={pendingRun ? runningIds.has(pendingRun.id) : false}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={pendingRun ? runningIds.has(pendingRun.id) : false}
              onClick={() => {
                if (!pendingRun) return;
                const wf = pendingRun;
                setPendingRun(null);
                void handleConfirmedRun(wf);
              }}
            >
              Run anyway
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <CreateWorkflowModal
        open={showCreate}
        onClose={() => setShowCreate(false)}
        onCreated={(wf) => {
          router.push(`/workspace/workflows/${wf.id}`);
        }}
      />
    </div>
  );
}
