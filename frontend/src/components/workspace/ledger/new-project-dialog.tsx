"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { createProject } from "@/core/ledger/api";
import { useLedgerWrite } from "@/core/ledger/hooks";

export function NewProjectDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const router = useRouter();
  const [name, setName] = useState("");
  const [why, setWhy] = useState("");
  const create = useLedgerWrite(createProject);

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (next) {
          setName("");
          setWhy("");
          create.reset();
        }
        onOpenChange(next);
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New project</DialogTitle>
          <DialogDescription>
            Something you are working toward. Goals and tasks come next.
          </DialogDescription>
        </DialogHeader>
        <form
          id="new-project"
          className="space-y-3"
          onSubmit={(event) => {
            event.preventDefault();
            create.mutate(
              { name: name.trim(), why: why.trim() || undefined },
              {
                onSuccess: (project) => {
                  onOpenChange(false);
                  router.push(`/workspace/projects/${project.id}`);
                },
              },
            );
          }}
        >
          <Input
            aria-label="Project name"
            placeholder="Beta launch"
            value={name}
            onChange={(event) => setName(event.target.value)}
            autoFocus
          />
          <Textarea
            aria-label="Why it matters"
            placeholder="Why it matters (optional)"
            rows={2}
            value={why}
            onChange={(event) => setWhy(event.target.value)}
          />
          {create.error != null && (
            <p className="text-destructive text-sm" role="alert">
              {create.error.message}
            </p>
          )}
        </form>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            type="submit"
            form="new-project"
            disabled={!name.trim() || create.isPending}
          >
            Create project
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
