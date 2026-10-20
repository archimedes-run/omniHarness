"use client";

import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { promoteTodos } from "@/core/ledger/api";
import { useLedgerWrite, useProjects } from "@/core/ledger/hooks";
import type { Todo } from "@/core/todos";

/** A chat's to-dos become project tasks (Feature 005 FR-012). The chat's own
 *  list is not changed. */
export function PromoteTodos({
  threadId,
  todos,
}: {
  threadId: string;
  todos: Todo[];
}) {
  const [open, setOpen] = useState(false);
  const { projects } = useProjects();
  const active = (projects ?? []).filter((p) => p.status !== "archived");
  const [projectId, setProjectId] = useState("");
  const [chosen, setChosen] = useState<Set<number>>(new Set());
  const promote = useLedgerWrite(promoteTodos);
  const items = todos.map((t) => (t.content ?? "").trim());

  return (
    <>
      <button
        type="button"
        className="text-muted-foreground hover:text-foreground text-xs"
        data-testid="promote-todos"
        onClick={(event) => {
          event.stopPropagation();
          setChosen(
            new Set(
              todos
                .map((t, i) => (t.status !== "completed" && items[i] ? i : -1))
                .filter((i) => i >= 0),
            ),
          );
          setProjectId(active[0]?.id ?? "");
          setOpen(true);
        }}
      >
        Add to a project
      </button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add to-dos to a project</DialogTitle>
            <DialogDescription>
              Each becomes a task linked to this chat. The chat&apos;s list
              stays as it is.
            </DialogDescription>
          </DialogHeader>
          {active.length === 0 ? (
            <p className="text-muted-foreground text-sm">
              There are no projects yet. Create one in Projects first.
            </p>
          ) : (
            <div className="space-y-3">
              <select
                aria-label="Project"
                className="border-input bg-background text-foreground w-full rounded-md border px-2 py-1.5 text-sm"
                value={projectId}
                onChange={(event) => setProjectId(event.target.value)}
              >
                {active.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
              <ul className="space-y-1" data-testid="promote-items">
                {items.map((title, index) =>
                  title ? (
                    <li key={index}>
                      <label className="flex items-center gap-2 text-sm">
                        <input
                          type="checkbox"
                          checked={chosen.has(index)}
                          onChange={() =>
                            setChosen((prev) => {
                              const next = new Set(prev);
                              if (next.has(index)) next.delete(index);
                              else next.add(index);
                              return next;
                            })
                          }
                        />
                        <span className="text-foreground">{title}</span>
                      </label>
                    </li>
                  ) : null,
                )}
              </ul>
              {promote.error != null && (
                <p className="text-destructive text-sm" role="alert">
                  {promote.error.message}
                </p>
              )}
            </div>
          )}
          <DialogFooter>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button
              disabled={!projectId || chosen.size === 0 || promote.isPending}
              onClick={() =>
                promote.mutate(
                  {
                    thread_id: threadId,
                    project_id: projectId,
                    titles: [...chosen].sort().map((i) => items[i]!),
                  },
                  {
                    onSuccess: (tasks) => {
                      setOpen(false);
                      const name = active.find((p) => p.id === projectId)?.name;
                      toast(
                        `Added ${tasks.length} task${tasks.length === 1 ? "" : "s"} to ${name}`,
                      );
                    },
                  },
                )
              }
            >
              {`Add ${chosen.size} task${chosen.size === 1 ? "" : "s"}`}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
