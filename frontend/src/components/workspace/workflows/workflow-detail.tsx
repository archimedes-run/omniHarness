"use client";

import {
  ArchiveIcon,
  ArrowLeftIcon,
  CheckCircleIcon,
  Loader2Icon,
  PencilIcon,
  PlayIcon,
  SparklesIcon,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { StatusBadge } from "@/components/workspace/status-badge";

import {
  archiveWorkflow,
  generateSpec,
  getWorkflow,
  patchWorkflow,
  triggerRun,
} from "./api";
import { RunList } from "./run-list";
import type { Workflow } from "./types";

type Tab = "overview" | "runs" | "settings";

const TABS: { label: string; value: Tab }[] = [
  { label: "Overview", value: "overview" },
  { label: "Runs", value: "runs" },
  { label: "Settings", value: "settings" },
];

interface WorkflowDetailProps {
  workflowId: string;
}

export function WorkflowDetail({ workflowId }: WorkflowDetailProps) {
  const router = useRouter();

  const [workflow, setWorkflow] = useState<Workflow | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<Tab>("overview");

  // Run state
  const [triggering, setTriggering] = useState(false);
  const [showRunConfirm, setShowRunConfirm] = useState(false);

  // Generate spec state
  const [generating, setGenerating] = useState(false);

  // Edit title state
  const [editingTitle, setEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");
  const [savingTitle, setSavingTitle] = useState(false);
  const titleInputRef = useRef<HTMLInputElement>(null);

  // Archive confirmation
  const [showArchiveConfirm, setShowArchiveConfirm] = useState(false);
  const [archiving, setArchiving] = useState(false);

  const loadWorkflow = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const wf = await getWorkflow(workflowId);
      setWorkflow(wf);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load workflow");
    } finally {
      setLoading(false);
    }
  }, [workflowId]);

  useEffect(() => {
    void loadWorkflow();
  }, [loadWorkflow]);

  const handleRun = async () => {
    if (!workflow || triggering) return;
    if (workflow.approval_policy === "approval_required") {
      setShowRunConfirm(true);
      return;
    }
    setTriggering(true);
    try {
      const run = await triggerRun(workflowId);
      router.push(`/workspace/workflows/${workflowId}/runs/${run.id}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to trigger run");
      setTriggering(false);
    }
  };

  const handleConfirmedRun = async () => {
    if (!workflow) return;
    setTriggering(true);
    try {
      const run = await triggerRun(workflowId, { confirmed: true });
      router.push(`/workspace/workflows/${workflowId}/runs/${run.id}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to trigger run");
      setTriggering(false);
    }
  };

  const handleGenerate = async () => {
    if (!workflow || generating) return;
    setGenerating(true);
    try {
      const spec = await generateSpec(workflowId);
      setWorkflow((prev) =>
        prev
          ? { ...prev, spec_json: spec, approval_policy: spec.approval_policy }
          : prev,
      );
      toast.success("Plan generated");
    } catch (err) {
      const msg =
        err instanceof Error ? err.message : "Failed to generate plan";
      if (msg.includes("409") || msg.toLowerCase().includes("no instruction")) {
        toast.error("No instruction to generate from");
      } else if (msg.includes("422")) {
        toast.error(msg);
      } else {
        toast.error(msg);
      }
    } finally {
      setGenerating(false);
    }
  };

  const handleEditTitle = () => {
    if (!workflow) return;
    setTitleDraft(workflow.title);
    setEditingTitle(true);
    setTimeout(() => titleInputRef.current?.focus(), 50);
  };

  const handleSaveTitle = async () => {
    if (!workflow || !titleDraft.trim() || savingTitle) return;
    if (titleDraft.trim() === workflow.title) {
      setEditingTitle(false);
      return;
    }
    setSavingTitle(true);
    try {
      const updated = await patchWorkflow(workflowId, {
        title: titleDraft.trim(),
      });
      setWorkflow(updated);
      setEditingTitle(false);
      toast.success("Title updated");
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Failed to update title",
      );
    } finally {
      setSavingTitle(false);
    }
  };

  const handlePatchApprovalPolicy = async (policy: string) => {
    if (!workflow) return;
    try {
      const updated = await patchWorkflow(workflowId, {
        approval_policy: policy,
      });
      setWorkflow(updated);
      toast.success("Approval policy updated");
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Failed to update approval policy",
      );
    }
  };

  const handleArchive = async () => {
    if (!workflow || archiving) return;
    setArchiving(true);
    try {
      const updated = await archiveWorkflow(workflowId);
      setWorkflow(updated);
      setShowArchiveConfirm(false);
      toast.success("Workflow archived");
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Failed to archive workflow",
      );
    } finally {
      setArchiving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex flex-1 items-center justify-center p-6">
        <Loader2Icon className="text-muted-foreground h-6 w-6 animate-spin" />
      </div>
    );
  }

  if (error || !workflow) {
    return (
      <div className="flex flex-1 flex-col gap-4 p-6">
        <Link
          href="/workspace/workflows"
          className="text-muted-foreground hover:text-foreground flex items-center gap-1.5 text-sm"
        >
          <ArrowLeftIcon className="h-4 w-4" />
          Workflows
        </Link>
        <div className="border-destructive/50 bg-destructive/10 text-destructive rounded-md border px-4 py-3 text-sm">
          {error ?? "Workflow not found"}
        </div>
      </div>
    );
  }

  const spec = workflow.spec_json;

  return (
    <div className="flex flex-1 flex-col gap-6 p-6">
      {/* Back link */}
      <Link
        href="/workspace/workflows"
        className="text-muted-foreground hover:text-foreground flex items-center gap-1.5 text-sm"
      >
        <ArrowLeftIcon className="h-4 w-4" />
        Workflows
      </Link>

      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-1">
          <div className="flex items-center gap-2">
            <h1 className="truncate text-2xl font-semibold">
              {workflow.title}
            </h1>
            <StatusBadge status={workflow.status} />
          </div>
          {workflow.description ? (
            <p className="text-muted-foreground text-sm">
              {workflow.description}
            </p>
          ) : null}
        </div>

        <Button
          onClick={() => void handleRun()}
          disabled={triggering}
          className="shrink-0 gap-1.5"
        >
          {triggering ? (
            <Loader2Icon className="h-4 w-4 animate-spin" />
          ) : (
            <PlayIcon className="h-4 w-4" />
          )}
          Run
        </Button>
      </div>

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

      {/* Tab content */}
      {activeTab === "overview" ? (
        <div className="flex flex-col gap-6">
          {/* Instruction prompt */}
          {workflow.instruction_prompt ? (
            <div className="flex flex-col gap-2">
              <h2 className="text-sm font-semibold">Instruction prompt</h2>
              <pre className="bg-muted rounded-md p-4 font-sans text-sm whitespace-pre-wrap">
                {workflow.instruction_prompt}
              </pre>
            </div>
          ) : (
            <div className="text-muted-foreground rounded-md border border-dashed p-4 text-center text-sm">
              No instruction prompt set. Go to Settings to add one.
            </div>
          )}

          {/* Plan / Spec */}
          <div className="flex flex-col gap-3">
            <div className="flex items-center justify-between gap-2">
              <h2 className="text-sm font-semibold">Plan</h2>
              <Button
                size="sm"
                variant="outline"
                disabled={generating}
                onClick={() => void handleGenerate()}
                className="gap-1.5"
              >
                {generating ? (
                  <Loader2Icon className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <SparklesIcon className="h-3.5 w-3.5" />
                )}
                {spec ? "Regenerate plan" : "Generate plan"}
              </Button>
            </div>

            {spec ? (
              <div className="rounded-lg border p-4">
                {spec.description ? (
                  <p className="text-muted-foreground mb-4 text-sm">
                    {spec.description}
                  </p>
                ) : null}

                <ol className="flex flex-col gap-4">
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
                          <div className="mt-1.5 flex flex-wrap gap-1">
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
                  <div className="mt-4 border-t pt-4">
                    <p className="mb-2 text-xs font-semibold">Risks</p>
                    <ul className="text-muted-foreground list-disc pl-4 text-xs">
                      {spec.risks.map((risk, i) => (
                        <li key={i}>{risk}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}

                {spec.required_capabilities.length > 0 ? (
                  <div className="mt-3">
                    <p className="mb-2 text-xs font-semibold">
                      Required capabilities
                    </p>
                    <div className="flex flex-wrap gap-1">
                      {spec.required_capabilities.map((cap) => (
                        <span
                          key={cap}
                          className="bg-muted text-muted-foreground rounded px-1.5 py-0.5 text-xs"
                        >
                          {cap}
                        </span>
                      ))}
                    </div>
                  </div>
                ) : null}

                {spec.approval_policy ? (
                  <div className="mt-3">
                    <p className="text-xs font-semibold">Approval policy</p>
                    <p className="text-muted-foreground mt-0.5 text-xs">
                      {spec.approval_policy}
                    </p>
                  </div>
                ) : null}
              </div>
            ) : (
              <div className="text-muted-foreground rounded-md border border-dashed p-4 text-center text-sm">
                No plan generated yet. Click &quot;Generate plan&quot; to create
                one.
              </div>
            )}
          </div>
        </div>
      ) : activeTab === "runs" ? (
        <RunList workflowId={workflowId} />
      ) : activeTab === "settings" ? (
        <div className="flex flex-col gap-6">
          {/* Edit title */}
          <div className="flex flex-col gap-2">
            <h2 className="text-sm font-semibold">Title</h2>
            {editingTitle ? (
              <div className="flex items-center gap-2">
                <input
                  ref={titleInputRef}
                  type="text"
                  className="bg-background focus:ring-ring min-w-0 flex-1 rounded-md border px-3 py-2 text-sm outline-none focus:ring-2"
                  value={titleDraft}
                  onChange={(e) => setTitleDraft(e.target.value)}
                  disabled={savingTitle}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") void handleSaveTitle();
                    if (e.key === "Escape") setEditingTitle(false);
                  }}
                />
                <Button
                  size="sm"
                  onClick={() => void handleSaveTitle()}
                  disabled={savingTitle || !titleDraft.trim()}
                >
                  {savingTitle ? (
                    <Loader2Icon className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <CheckCircleIcon className="h-3.5 w-3.5" />
                  )}
                  Save
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setEditingTitle(false)}
                  disabled={savingTitle}
                >
                  Cancel
                </Button>
              </div>
            ) : (
              <div className="flex items-center gap-2">
                <p className="text-sm">{workflow.title}</p>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={handleEditTitle}
                  className="gap-1.5"
                >
                  <PencilIcon className="h-3.5 w-3.5" />
                  Edit
                </Button>
              </div>
            )}
          </div>

          {/* Approval policy */}
          <div className="flex flex-col gap-2">
            <h2 className="text-sm font-semibold">Approval policy</h2>
            <p className="text-muted-foreground text-sm">
              Controls whether a run requires explicit confirmation before
              executing.
            </p>
            <select
              className="bg-background focus:ring-ring w-full max-w-xs rounded-md border px-3 py-2 text-sm outline-none focus:ring-2"
              value={workflow.approval_policy ?? "draft_only"}
              onChange={(e) => void handlePatchApprovalPolicy(e.target.value)}
            >
              <option value="draft_only">Manual only (draft_only)</option>
              <option value="execute_low_risk">
                Auto-execute low-risk (execute_low_risk)
              </option>
              <option value="approval_required">
                Require confirmation (approval_required)
              </option>
            </select>
          </div>

          {/* Archive */}
          <div className="flex flex-col gap-2">
            <h2 className="text-sm font-semibold">Archive workflow</h2>
            <p className="text-muted-foreground text-sm">
              Archived workflows are hidden from the default list but their run
              history is preserved.
            </p>
            <div>
              <Button
                variant="destructive"
                size="sm"
                disabled={workflow.status === "archived"}
                onClick={() => setShowArchiveConfirm(true)}
                className="gap-1.5"
              >
                <ArchiveIcon className="h-3.5 w-3.5" />
                {workflow.status === "archived"
                  ? "Already archived"
                  : "Archive workflow"}
              </Button>
            </div>
          </div>
        </div>
      ) : null}

      {/* Run confirmation dialog */}
      <Dialog
        open={showRunConfirm}
        onOpenChange={(v) => !v && setShowRunConfirm(false)}
      >
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>Run workflow?</DialogTitle>
          </DialogHeader>
          <p className="text-muted-foreground text-sm">
            &quot;{workflow.title}&quot; may take irreversible or external
            actions. Run anyway?
          </p>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setShowRunConfirm(false)}
              disabled={triggering}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => {
                setShowRunConfirm(false);
                void handleConfirmedRun();
              }}
              disabled={triggering}
            >
              Run anyway
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Archive confirmation dialog */}
      <Dialog
        open={showArchiveConfirm}
        onOpenChange={(v) => !v && setShowArchiveConfirm(false)}
      >
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>Archive workflow?</DialogTitle>
          </DialogHeader>
          <p className="text-muted-foreground text-sm">
            This will archive &quot;{workflow.title}&quot;. You can still access
            it from the Archived tab.
          </p>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setShowArchiveConfirm(false)}
              disabled={archiving}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => void handleArchive()}
              disabled={archiving}
            >
              {archiving ? (
                <Loader2Icon className="mr-1.5 h-3.5 w-3.5 animate-spin" />
              ) : null}
              Archive
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
