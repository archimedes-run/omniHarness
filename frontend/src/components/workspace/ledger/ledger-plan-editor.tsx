"use client";

import { XIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export type LedgerChange = Record<string, unknown> & { op: string };

/** The fields a person may change, per kind of change. Ids, refs and the
 *  project a change belongs to are not edited here: a typo fix should not be
 *  able to move a task to another project unseen. */
const FIELDS: Record<string, { key: string; label: string; type?: string }[]> =
  {
    create_project: [
      { key: "name", label: "Project name" },
      { key: "why", label: "Why" },
    ],
    create_goal: [
      { key: "title", label: "Goal" },
      { key: "definition_of_done", label: "Done when" },
      { key: "target_date", label: "Target date", type: "date" },
    ],
    create_task: [
      { key: "title", label: "Task" },
      { key: "due_date", label: "Due", type: "date" },
    ],
    update_task: [
      { key: "title", label: "Task" },
      { key: "due_date", label: "Due", type: "date" },
    ],
    add_note: [
      { key: "decided", label: "Decision" },
      { key: "why", label: "Why" },
    ],
    link_thread: [],
  };

const VERB: Record<string, string> = {
  create_project: "New project",
  create_goal: "New goal",
  create_task: "New task",
  update_task: "Change task",
  add_note: "Decision",
  link_thread: "Attach this chat",
};

/** Edit a ledger_apply plan before confirming it (Feature 005 FR-010). */
export function LedgerPlanEditor({
  changes,
  onChange,
}: {
  changes: LedgerChange[];
  onChange: (changes: LedgerChange[]) => void;
}) {
  const set = (index: number, key: string, value: string) =>
    onChange(
      changes.map((change, i) => {
        if (i !== index) return change;
        const next = { ...change };
        if (value === "") delete next[key];
        else next[key] = value;
        return next;
      }),
    );
  const remove = (index: number) =>
    onChange(changes.filter((_, i) => i !== index));
  // A project created earlier in this plan is named, not shown by its ref.
  const names = new Map(
    changes
      .filter((c) => c.op === "create_project" && typeof c.ref === "string")
      .map((c) => [c.ref as string, String(c.name ?? c.ref)]),
  );

  return (
    <ul className="space-y-2" data-testid="plan-editor">
      {changes.map((change, index) => (
        <li key={index} className="space-y-1.5 rounded-md border p-2">
          <div className="flex items-center justify-between">
            <p className="text-muted-foreground text-xs">
              {VERB[change.op] ?? change.op}
              {typeof change.project === "string" &&
              change.op !== "create_project"
                ? ` · ${names.get(change.project) ?? change.project}`
                : ""}
            </p>
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="Remove this change"
              onClick={() => remove(index)}
            >
              <XIcon />
            </Button>
          </div>
          {(FIELDS[change.op] ?? []).map((field) => (
            <Input
              key={field.key}
              aria-label={field.label}
              placeholder={field.label}
              type={field.type ?? "text"}
              className="h-8"
              value={
                typeof change[field.key] === "string"
                  ? (change[field.key] as string)
                  : ""
              }
              onChange={(event) => set(index, field.key, event.target.value)}
            />
          ))}
        </li>
      ))}
    </ul>
  );
}
