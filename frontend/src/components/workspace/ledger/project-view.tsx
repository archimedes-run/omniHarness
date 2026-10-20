"use client";

import { ArrowLeftIcon, PlusIcon, XIcon } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import {
  LedgerError,
  createGoal,
  createNote,
  createTask,
  detachLink,
  patchProject,
  patchTask,
} from "@/core/ledger/api";
import { useLedgerWrite, useProject } from "@/core/ledger/hooks";
import type {
  Goal,
  ProjectStatus,
  Task,
  TaskStatus,
} from "@/core/ledger/types";
import { formatTimeAgo } from "@/core/utils/datetime";
import { cn } from "@/lib/utils";

const SELECT =
  "border-input bg-background text-foreground rounded-md border px-2 py-1 text-xs";

const GROUPS: { status: TaskStatus; label: string }[] = [
  { status: "doing", label: "Doing" },
  { status: "blocked", label: "Blocked" },
  { status: "todo", label: "To do" },
  { status: "done", label: "Done" },
  { status: "dropped", label: "Dropped" },
];

/** A stale edit (another tab changed it) says so; everything re-reads. */
function onWriteError(error: Error) {
  toast.error(
    error instanceof LedgerError && error.status === 409
      ? "This changed since you opened it. Showing the latest."
      : error.message,
  );
}

function dueLabel(due: string | null): { text: string; overdue: boolean } {
  if (!due) return { text: "", overdue: false };
  const today = new Date().toISOString().slice(0, 10);
  return { text: `due ${due}`, overdue: due < today };
}

function Section({
  title,
  action,
  children,
}: {
  title: string;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-2">
      <div className="flex items-center justify-between">
        <h2 className="text-muted-foreground text-xs font-medium tracking-wide uppercase">
          {title}
        </h2>
        {action}
      </div>
      {children}
    </section>
  );
}

/** The Project view (Feature 005, contracts/ui.md). One primary action: Add task. */
export function ProjectView({ projectId }: { projectId: string }) {
  const { view, error, isLoading } = useProject(projectId);
  const [adding, setAdding] = useState(false);

  if (isLoading) {
    return (
      <div className="space-y-3" data-testid="project-loading">
        <Skeleton className="h-8 w-1/2" />
        <Skeleton className="h-24" />
        <Skeleton className="h-40" />
      </div>
    );
  }
  if (error != null || !view) {
    return (
      <p className="text-destructive text-sm" role="alert">
        {error instanceof LedgerError && error.status === 404
          ? "There is no such project."
          : `I can't read this project: ${error?.message ?? "unknown error"}`}
      </p>
    );
  }

  const { project, goals, tasks, notes, links } = view;
  const chats = links.filter((link) => link.to_kind === "thread");

  return (
    <div className="space-y-8" data-testid="project-view">
      <div className="space-y-3">
        <Link
          href="/workspace/projects"
          className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-xs"
        >
          <ArrowLeftIcon className="size-3" />
          Projects
        </Link>
        <header className="flex items-start justify-between gap-4">
          <div className="min-w-0 space-y-1">
            <h1 className="text-xl font-semibold">{project.name}</h1>
            {project.why && (
              <p className="text-muted-foreground text-sm">{project.why}</p>
            )}
            <p className="text-muted-foreground text-xs">
              <ProjectStatusSelect
                id={project.id}
                status={project.status}
                version={project.version}
              />
              <span className="ml-2">{`Updated ${formatTimeAgo(project.updated_at)}`}</span>
            </p>
          </div>
          <Button onClick={() => setAdding(true)}>
            <PlusIcon />
            Add task
          </Button>
        </header>
      </div>

      <Goals projectId={project.id} goals={goals} />

      <Section title="Tasks">
        {adding && (
          <AddTask
            projectId={project.id}
            goals={goals}
            onDone={() => setAdding(false)}
          />
        )}
        {tasks.length === 0 && !adding ? (
          <p
            className="text-muted-foreground text-sm"
            data-testid="tasks-empty"
          >
            No tasks yet.
          </p>
        ) : (
          GROUPS.map(({ status, label }) => {
            const group = tasks.filter((task) => task.status === status);
            if (group.length === 0) return null;
            return (
              <div key={status} className="space-y-1" data-group={status}>
                <p className="text-muted-foreground text-xs">{`${label} · ${group.length}`}</p>
                <ul className="divide-border divide-y rounded-lg border">
                  {group.map((task) => (
                    <TaskRow key={task.id} task={task} />
                  ))}
                </ul>
              </div>
            );
          })
        )}
      </Section>

      <Decisions projectId={project.id} notes={notes} />

      <Section title="Linked chats">
        {chats.length === 0 ? (
          <p className="text-muted-foreground text-sm">
            No chats yet. Attach one from its header, or promote a chat&apos;s
            to-dos here.
          </p>
        ) : (
          <ul className="space-y-1" data-testid="linked-chats">
            {chats.map((link) => (
              <ChatLink
                key={link.id}
                id={link.id}
                threadId={link.to_ref}
                label={link.label}
              />
            ))}
          </ul>
        )}
      </Section>
    </div>
  );
}

function ProjectStatusSelect({
  id,
  status,
  version,
}: {
  id: string;
  status: ProjectStatus;
  version: number;
}) {
  const write = useLedgerWrite((next: ProjectStatus) =>
    patchProject(id, { status: next, version }),
  );
  return (
    <select
      aria-label="Project status"
      className={SELECT}
      value={status}
      onChange={(event) =>
        write.mutate(event.target.value as ProjectStatus, {
          onError: onWriteError,
        })
      }
    >
      {(["active", "paused", "done", "archived"] as const).map((value) => (
        <option key={value} value={value}>
          {value}
        </option>
      ))}
    </select>
  );
}

function Goals({ projectId, goals }: { projectId: string; goals: Goal[] }) {
  const [adding, setAdding] = useState(false);
  const [title, setTitle] = useState("");
  const [done, setDone] = useState("");
  const [target, setTarget] = useState("");
  const create = useLedgerWrite(() =>
    createGoal(projectId, {
      title: title.trim(),
      definition_of_done: done.trim(),
      target_date: target || undefined,
    }),
  );
  return (
    <Section
      title="Goals"
      action={
        !adding && (
          <Button variant="ghost" size="sm" onClick={() => setAdding(true)}>
            <PlusIcon />
            Add goal
          </Button>
        )
      }
    >
      {goals.length === 0 && !adding && (
        <p className="text-muted-foreground text-sm">No goals yet.</p>
      )}
      <ul className="space-y-2">
        {goals.map((goal) => {
          const pct = goal.progress.total
            ? (goal.progress.done / goal.progress.total) * 100
            : 0;
          return (
            <li key={goal.id} className="space-y-1" data-testid="goal">
              <div className="flex items-baseline justify-between gap-4">
                <p className="text-foreground text-sm font-medium">
                  {goal.title}
                </p>
                <p className="text-muted-foreground shrink-0 text-xs">
                  {`${goal.progress.done} of ${goal.progress.total} done`}
                  {goal.target_date && ` · target ${goal.target_date}`}
                </p>
              </div>
              <div className="bg-muted h-1 overflow-hidden rounded-full">
                <div
                  className="bg-foreground/60 h-full"
                  style={{ width: `${pct}%` }}
                />
              </div>
              <p className="text-muted-foreground text-xs">{`Done when ${goal.definition_of_done}`}</p>
            </li>
          );
        })}
      </ul>
      {adding && (
        <form
          className="space-y-2 rounded-lg border p-3"
          onSubmit={(event) => {
            event.preventDefault();
            create.mutate(undefined, {
              onSuccess: () => {
                setAdding(false);
                setTitle("");
                setDone("");
                setTarget("");
              },
              onError: onWriteError,
            });
          }}
        >
          <Input
            aria-label="Goal"
            placeholder="Public beta live"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            autoFocus
          />
          <Input
            aria-label="Done when"
            placeholder="Done when… anyone can sign up"
            value={done}
            onChange={(e) => setDone(e.target.value)}
          />
          <div className="flex items-center justify-between gap-2">
            <Input
              aria-label="Target date"
              type="date"
              className="w-auto"
              value={target}
              onChange={(e) => setTarget(e.target.value)}
            />
            <div className="flex gap-2">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => setAdding(false)}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                variant="outline"
                size="sm"
                disabled={!title.trim() || !done.trim() || create.isPending}
              >
                Save goal
              </Button>
            </div>
          </div>
        </form>
      )}
    </Section>
  );
}

function AddTask({
  projectId,
  goals,
  onDone,
}: {
  projectId: string;
  goals: Goal[];
  onDone: () => void;
}) {
  const [title, setTitle] = useState("");
  const [due, setDue] = useState("");
  const [goal, setGoal] = useState("");
  const create = useLedgerWrite(() =>
    createTask(projectId, {
      title: title.trim(),
      due_date: due || undefined,
      goal_id: goal || undefined,
      owner: "me",
    }),
  );
  return (
    <form
      className="flex flex-wrap items-center gap-2 rounded-lg border p-2"
      data-testid="add-task"
      onSubmit={(event) => {
        event.preventDefault();
        create.mutate(undefined, { onSuccess: onDone, onError: onWriteError });
      }}
    >
      <Input
        aria-label="Task"
        placeholder="What needs doing"
        className="min-w-48 flex-1"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        autoFocus
      />
      <Input
        aria-label="Due date"
        type="date"
        className="w-auto"
        value={due}
        onChange={(e) => setDue(e.target.value)}
      />
      {goals.length > 0 && (
        <select
          aria-label="Goal"
          className={SELECT}
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
        >
          <option value="">No goal</option>
          {goals.map((g) => (
            <option key={g.id} value={g.id}>
              {g.title}
            </option>
          ))}
        </select>
      )}
      <Button type="button" variant="ghost" size="sm" onClick={onDone}>
        Cancel
      </Button>
      <Button
        type="submit"
        variant="outline"
        size="sm"
        disabled={!title.trim() || create.isPending}
      >
        Add
      </Button>
    </form>
  );
}

function TaskRow({ task }: { task: Task }) {
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(task.title);
  const write = useLedgerWrite((body: Parameters<typeof patchTask>[1]) =>
    patchTask(task.id, body),
  );
  const due = dueLabel(task.status === "done" ? null : task.due_date);

  return (
    <li
      className="group flex items-center gap-3 px-3 py-2"
      data-testid="task"
      data-status={task.status}
    >
      <span className="text-muted-foreground w-10 shrink-0 font-mono text-xs">
        {task.short_id}
      </span>
      {editing ? (
        <form
          className="flex flex-1 gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            write.mutate(
              { version: task.version, title: title.trim() },
              { onSuccess: () => setEditing(false), onError: onWriteError },
            );
          }}
        >
          <Input
            aria-label="Task title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            autoFocus
            className="h-8"
          />
          <Button
            type="submit"
            size="sm"
            variant="outline"
            disabled={!title.trim()}
          >
            Save
          </Button>
        </form>
      ) : (
        <button
          type="button"
          className={cn(
            "min-w-0 flex-1 truncate text-left text-sm",
            task.status === "done" || task.status === "dropped"
              ? "text-muted-foreground line-through"
              : "text-foreground",
          )}
          title="Edit"
          onClick={() => {
            setTitle(task.title);
            setEditing(true);
          }}
        >
          {task.title}
        </button>
      )}
      {due.text && (
        <span
          className={cn(
            "shrink-0 text-xs",
            due.overdue ? "text-destructive" : "text-muted-foreground",
          )}
          data-testid="due"
        >
          {due.overdue ? `overdue · ${task.due_date}` : due.text}
        </span>
      )}
      {task.owner && task.owner.kind !== "user" && (
        <span className="text-muted-foreground shrink-0 text-xs">
          {task.owner.kind}
        </span>
      )}
      {/* FR-013: changing status is the user's own action, here. */}
      <select
        aria-label={`Status of ${task.short_id}`}
        className={SELECT}
        value={task.status}
        onChange={(event) =>
          write.mutate(
            { version: task.version, status: event.target.value as TaskStatus },
            { onError: onWriteError },
          )
        }
      >
        {GROUPS.map(({ status, label }) => (
          <option key={status} value={status}>
            {label}
          </option>
        ))}
      </select>
    </li>
  );
}

function Decisions({
  projectId,
  notes,
}: {
  projectId: string;
  notes: {
    id: string;
    decided: string;
    why: string | null;
    created_at: string;
  }[];
}) {
  const [adding, setAdding] = useState(false);
  const [decided, setDecided] = useState("");
  const [why, setWhy] = useState("");
  const create = useLedgerWrite(() =>
    createNote(projectId, {
      decided: decided.trim(),
      why: why.trim() || undefined,
    }),
  );
  return (
    <Section
      title="Decisions"
      action={
        !adding && (
          <Button variant="ghost" size="sm" onClick={() => setAdding(true)}>
            <PlusIcon />
            Record decision
          </Button>
        )
      }
    >
      {notes.length === 0 && !adding && (
        <p className="text-muted-foreground text-sm">No decisions recorded.</p>
      )}
      <ul className="space-y-2">
        {notes.map((note) => (
          <li key={note.id} className="space-y-0.5" data-testid="decision">
            <p className="text-foreground text-sm">{note.decided}</p>
            <p className="text-muted-foreground text-xs">
              {note.why ? `${note.why} · ` : ""}
              {formatTimeAgo(note.created_at)}
            </p>
          </li>
        ))}
      </ul>
      {adding && (
        <form
          className="space-y-2 rounded-lg border p-3"
          onSubmit={(event) => {
            event.preventDefault();
            create.mutate(undefined, {
              onSuccess: () => {
                setAdding(false);
                setDecided("");
                setWhy("");
              },
              onError: onWriteError,
            });
          }}
        >
          <Textarea
            aria-label="Decision"
            placeholder="What was decided"
            rows={2}
            value={decided}
            onChange={(e) => setDecided(e.target.value)}
            autoFocus
          />
          <Input
            aria-label="Why"
            placeholder="Why (optional)"
            value={why}
            onChange={(e) => setWhy(e.target.value)}
          />
          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => setAdding(false)}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              variant="outline"
              size="sm"
              disabled={!decided.trim() || create.isPending}
            >
              Save
            </Button>
          </div>
        </form>
      )}
    </Section>
  );
}

function ChatLink({
  id,
  threadId,
  label,
}: {
  id: string;
  threadId: string;
  label: string | null;
}) {
  const detach = useLedgerWrite(() => detachLink(id));
  return (
    <li className="group flex items-center justify-between gap-2 text-sm">
      <Link
        href={`/workspace/chats/${threadId}`}
        className="text-foreground truncate hover:underline"
      >
        {label?.trim() ? label : `Chat ${threadId.slice(0, 8)}`}
      </Link>
      <Button
        variant="ghost"
        size="icon-sm"
        aria-label="Detach chat"
        className="text-muted-foreground opacity-0 group-hover:opacity-100 focus-visible:opacity-100"
        onClick={() => detach.mutate(undefined, { onError: onWriteError })}
      >
        <XIcon />
      </Button>
    </li>
  );
}
