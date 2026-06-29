"use client";

import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

import { createWorkflow } from "./api";
import type { Workflow } from "./types";

interface CreateWorkflowModalProps {
  open: boolean;
  onClose: () => void;
  onCreated: (wf: Workflow) => void;
}

export function CreateWorkflowModal({
  open,
  onClose,
  onCreated,
}: CreateWorkflowModalProps) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [instructionPrompt, setInstructionPrompt] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const titleRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) {
      setTitle("");
      setDescription("");
      setInstructionPrompt("");
      setError(null);
      setSubmitting(false);
      // Focus title after the dialog renders
      setTimeout(() => titleRef.current?.focus(), 50);
    }
  }, [open]);

  const handleSubmit = async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (!title.trim() || submitting) return;

    setSubmitting(true);
    setError(null);

    try {
      const wf = await createWorkflow({
        title: title.trim(),
        description: description.trim() || undefined,
        instruction_prompt: instructionPrompt.trim() || undefined,
      });
      onCreated(wf);
      onClose();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to create workflow",
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Create workflow</DialogTitle>
        </DialogHeader>

        <form
          onSubmit={(e) => void handleSubmit(e)}
          className="flex flex-col gap-4"
        >
          <div className="flex flex-col gap-1.5">
            <label htmlFor="wf-title" className="text-sm font-medium">
              Title <span className="text-destructive">*</span>
            </label>
            <input
              id="wf-title"
              ref={titleRef}
              type="text"
              className="bg-background focus:ring-ring rounded-md border px-3 py-2 text-sm outline-none focus:ring-2"
              placeholder="e.g. Weekly report generation"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              disabled={submitting}
              required
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <label htmlFor="wf-description" className="text-sm font-medium">
              Description{" "}
              <span className="text-muted-foreground font-normal">
                (optional)
              </span>
            </label>
            <textarea
              id="wf-description"
              className="bg-background focus:ring-ring rounded-md border px-3 py-2 text-sm outline-none focus:ring-2"
              placeholder="Brief description of what this workflow does"
              rows={2}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              disabled={submitting}
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <label htmlFor="wf-instruction" className="text-sm font-medium">
              Instruction prompt{" "}
              <span className="text-muted-foreground font-normal">
                (optional)
              </span>
            </label>
            <textarea
              id="wf-instruction"
              className="bg-background focus:ring-ring rounded-md border px-3 py-2 text-sm outline-none focus:ring-2"
              placeholder="Detailed instructions for the agent to follow when executing this workflow"
              rows={4}
              value={instructionPrompt}
              onChange={(e) => setInstructionPrompt(e.target.value)}
              disabled={submitting}
            />
          </div>

          {error ? <p className="text-destructive text-sm">{error}</p> : null}

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={onClose}
              disabled={submitting}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={submitting || !title.trim()}>
              {submitting ? "Creating…" : "Create workflow"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
