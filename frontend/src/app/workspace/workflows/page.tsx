"use client";

import { GitBranchIcon } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { fetch } from "@/core/api/fetcher";

interface Workflow {
  id: string;
  owner_id: string | null;
  title: string;
  description: string | null;
  status: string;
  created_at: string;
  updated_at: string;
}

function statusVariant(
  status: string,
): "default" | "secondary" | "destructive" | "outline" {
  switch (status) {
    case "active":
      return "default";
    case "paused":
      return "secondary";
    case "archived":
      return "outline";
    default:
      return "secondary";
  }
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return iso;
  }
}

export default function WorkflowsPage() {
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [creating, setCreating] = useState(false);
  const [formTitle, setFormTitle] = useState("");
  const [formDescription, setFormDescription] = useState("");

  const loadWorkflows = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/workflows");
      if (!res.ok) {
        throw new Error(`Failed to load workflows: ${res.status}`);
      }
      const data = (await res.json()) as Workflow[];
      setWorkflows(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load workflows");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadWorkflows();
  }, [loadWorkflows]);

  const handleCreate = async () => {
    if (!formTitle.trim()) return;
    setCreating(true);
    try {
      const res = await fetch("/api/workflows", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: formTitle.trim(),
          description: formDescription.trim() || null,
        }),
      });
      if (!res.ok) {
        throw new Error(`Failed to create workflow: ${res.status}`);
      }
      setFormTitle("");
      setFormDescription("");
      setShowForm(false);
      await loadWorkflows();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to create workflow",
      );
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="flex flex-1 flex-col gap-6 p-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <GitBranchIcon className="h-6 w-6" />
          <h1 className="text-2xl font-semibold">Workflows</h1>
        </div>
        <button
          className="bg-primary text-primary-foreground hover:bg-primary/90 rounded-md px-4 py-2 text-sm font-medium"
          onClick={() => setShowForm((v) => !v)}
        >
          New workflow
        </button>
      </div>

      {showForm && (
        <div className="bg-card rounded-lg border p-4 shadow-sm">
          <h2 className="mb-3 text-sm font-medium">Create workflow</h2>
          <div className="flex flex-col gap-3">
            <input
              autoFocus
              className="bg-background focus:ring-ring rounded-md border px-3 py-2 text-sm outline-none focus:ring-2"
              placeholder="Title"
              type="text"
              value={formTitle}
              onChange={(e) => setFormTitle(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  void handleCreate();
                }
              }}
            />
            <textarea
              className="bg-background focus:ring-ring rounded-md border px-3 py-2 text-sm outline-none focus:ring-2"
              placeholder="Description (optional)"
              rows={2}
              value={formDescription}
              onChange={(e) => setFormDescription(e.target.value)}
            />
            <div className="flex gap-2">
              <button
                className="bg-primary text-primary-foreground hover:bg-primary/90 rounded-md px-3 py-1.5 text-sm font-medium disabled:opacity-50"
                disabled={creating || !formTitle.trim()}
                onClick={() => void handleCreate()}
              >
                {creating ? "Creating…" : "Create"}
              </button>
              <button
                className="hover:bg-muted rounded-md border px-3 py-1.5 text-sm font-medium"
                onClick={() => {
                  setShowForm(false);
                  setFormTitle("");
                  setFormDescription("");
                }}
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {error && (
        <div className="border-destructive/50 bg-destructive/10 text-destructive rounded-md border px-4 py-3 text-sm">
          {error}
        </div>
      )}

      {loading ? (
        <div className="text-muted-foreground flex flex-1 items-center justify-center">
          Loading…
        </div>
      ) : workflows.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 text-center">
          <GitBranchIcon className="text-muted-foreground/40 h-12 w-12" />
          <div>
            <p className="text-base font-medium">No workflows yet</p>
            <p className="text-muted-foreground mt-1 text-sm">
              Create your first workflow to get started.
            </p>
          </div>
        </div>
      ) : (
        <div className="grid gap-3">
          {workflows.map((wf) => (
            <div
              key={wf.id}
              className="bg-card hover:bg-muted/30 rounded-lg border p-4 shadow-sm transition-colors"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0 flex-1">
                  <p className="truncate font-medium">{wf.title}</p>
                  {wf.description && (
                    <p className="text-muted-foreground mt-0.5 line-clamp-2 text-sm">
                      {wf.description}
                    </p>
                  )}
                  <p className="text-muted-foreground mt-1.5 text-xs">
                    Created {formatDate(wf.created_at)}
                  </p>
                </div>
                <Badge variant={statusVariant(wf.status)}>{wf.status}</Badge>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
