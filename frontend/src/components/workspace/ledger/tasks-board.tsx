"use client";

import { useQueries } from "@tanstack/react-query";
import { ExternalLinkIcon, PlusIcon } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { BrandLogo } from "@/components/brand";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  LedgerError,
  createNote,
  createTask,
  loadProject,
  patchTask,
} from "@/core/ledger/api";
import {
  dueWords,
  groupTasks,
  ownerWords,
  progress,
  statusWords,
} from "@/core/ledger/board";
import { useLedgerWrite, useProject, useProjects } from "@/core/ledger/hooks";
import type {
  Link as LedgerLink,
  ProjectSummary,
  ProjectView,
  Task,
} from "@/core/ledger/types";
import { useThreads } from "@/core/threads/queries";
import { cn } from "@/lib/utils";

import { NewProjectDialog } from "./new-project-dialog";

/** "all" is every open task across projects; otherwise a project id. */
export type TasksSelection = string | null;

const TONE: Record<string, string> = {
  warn: "text-warning",
  good: "text-success",
  bad: "text-destructive",
  muted: "text-muted-foreground",
};

function onWriteError(error: Error) {
  toast.error(
    error instanceof LedgerError && error.status === 409
      ? "This changed since you opened it. Showing the latest."
      : error.message,
  );
}

/**
 * The Tasks panel (Feature 006, Tasks.dc.html): projects on the left, the
 * chosen project's tasks on the right, grouped In progress / To do / Done
 * this week, each with its owner, status and date. The plan is the user's
 * (Feature 005): evidence, observed or reported, never changes a status.
 */
export function TasksBoard({
  selection,
  onSelect,
}: {
  selection: TasksSelection;
  onSelect: (next: TasksSelection) => void;
}) {
  const { projects, error, isLoading } = useProjects();
  const [creating, setCreating] = useState(false);
  const active = useMemo(
    () => (projects ?? []).filter((p) => p.status === "active"),
    [projects],
  );
  const listed = projects ?? [];
  // Nothing chosen: the most recently updated active project.
  const current =
    selection ??
    [...active].sort((a, b) => b.updated_at.localeCompare(a.updated_at))[0]
      ?.id ??
    (listed.length > 0 ? "all" : null);
  const openTotal = listed.reduce((n, p) => n + p.open_tasks, 0);

  return (
    <div
      className="flex min-h-full flex-col md:flex-row"
      data-testid="tasks-board"
    >
      <nav
        aria-label="Projects"
        className="border-border flex shrink-0 flex-col gap-1 border-b px-2.5 py-3.5 md:w-[260px] md:border-r md:border-b-0"
      >
        <button
          type="button"
          onClick={() => setCreating(true)}
          className="border-border-strong text-foreground hover:bg-accent mb-2 flex min-h-11 items-center gap-1.5 rounded-lg border border-dashed px-3 text-left text-sm md:min-h-9"
        >
          <PlusIcon className="size-3.5" aria-hidden />
          New project
        </button>
        {isLoading && (
          <div className="flex flex-col gap-2" data-testid="projects-loading">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-9 rounded-lg" />
            ))}
          </div>
        )}
        {projects && (
          <NavItem
            label="All open tasks"
            count={openTotal}
            active={current === "all"}
            onClick={() => onSelect("all")}
          />
        )}
        {listed.length > 0 && (
          <div className="bg-border mx-1 my-1.5 h-px" aria-hidden />
        )}
        <ul className="flex flex-col gap-1">
          {listed.map((p) => (
            <li key={p.id}>
              <NavItem
                label={p.name}
                count={p.open_tasks}
                note={p.status !== "active" ? p.status : undefined}
                active={current === p.id}
                onClick={() => onSelect(p.id)}
                testId="project"
              />
            </li>
          ))}
        </ul>
      </nav>

      <div className="flex min-w-0 flex-1 flex-col gap-[18px] px-4 py-5 md:px-7">
        {error != null && (
          <Alert variant="destructive" data-testid="projects-unreadable">
            <AlertTitle>I can&apos;t read your projects</AlertTitle>
            <AlertDescription>{error.message}</AlertDescription>
          </Alert>
        )}
        {projects?.length === 0 && (
          <div
            className="text-muted-foreground rounded-lg border border-dashed p-8 text-center text-sm"
            data-testid="projects-empty"
          >
            No projects yet. Tell the assistant what you&apos;re working toward,
            or create one with New project.
          </div>
        )}
        {current === "all" && projects && (
          <AllOpenTasks projects={listed} onOpen={onSelect} />
        )}
        {current && current !== "all" && (
          <ProjectPane key={current} projectId={current} />
        )}
      </div>

      <NewProjectDialog
        open={creating}
        onOpenChange={setCreating}
        onCreated={(id) => onSelect(id)}
      />
    </div>
  );
}

function NavItem({
  label,
  count,
  note,
  active,
  onClick,
  testId,
}: {
  label: string;
  count: number;
  note?: string;
  active: boolean;
  onClick: () => void;
  testId?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-current={active ? "true" : undefined}
      data-testid={testId}
      className={cn(
        "flex min-h-11 w-full items-center justify-between gap-2 rounded-lg px-3 text-left text-sm md:min-h-9",
        active
          ? "bg-surface-raised text-foreground font-medium"
          : "text-foreground-2 hover:bg-accent",
      )}
    >
      <span className="min-w-0 truncate">
        {label}
        {note && (
          <span className="text-muted-foreground ml-2 text-xs font-normal">
            {note}
          </span>
        )}
      </span>
      <span className="text-muted-foreground font-normal">{count}</span>
    </button>
  );
}

function ProjectPane({ projectId }: { projectId: string }) {
  const { view, error, isLoading } = useProject(projectId);
  const { data: threads } = useThreads();
  if (isLoading) {
    return (
      <div className="flex flex-col gap-3" data-testid="project-loading">
        <Skeleton className="h-8 w-1/2" />
        <Skeleton className="h-24" />
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
  const titles = new Map(
    (threads ?? []).map((t) => [t.thread_id, t.values?.title ?? ""]),
  );
  return <Project view={view} titles={titles} />;
}

function Project({
  view,
  titles,
}: {
  view: ProjectView;
  titles: Map<string, string>;
}) {
  const { project, goals, tasks, notes, links } = view;
  const { done, total } = progress(tasks);
  const goal = goals[0];
  const percent = total === 0 ? 0 : Math.round((done / total) * 100);
  const chats = links.filter((l) => l.to_kind === "thread");
  return (
    <div className="flex flex-col gap-[18px]" data-testid="project-pane">
      <Tabs defaultValue="tasks" className="gap-[18px]">
        <div className="flex flex-wrap items-end gap-4">
          <div className="min-w-0 flex-[1_1_300px]">
            <h2 className="flex items-center gap-2 text-xl font-semibold">
              {project.name}
              <Link
                href={`/workspace/projects/${project.id}`}
                aria-label={`Open ${project.name} as a page`}
                className="text-muted-foreground hover:text-foreground inline-flex size-8 items-center justify-center rounded-md"
              >
                <ExternalLinkIcon className="size-4" aria-hidden />
              </Link>
            </h2>
            <p className="text-muted-foreground" data-testid="project-goal">
              {goal ? `Goal: ${goal.title}` : "No goal yet"} ·{" "}
              {`${done} of ${total} ${total === 1 ? "task" : "tasks"} done`}
            </p>
          </div>
          <TabsList
            variant="line"
            aria-label="Project views"
            className="h-auto gap-1"
          >
            {["Tasks", "Evidence", "Decisions", "Chats"].map((label) => (
              <TabsTrigger
                key={label}
                value={label.toLowerCase()}
                className="text-foreground-2 data-[state=active]:bg-surface-raised data-[state=active]:text-foreground min-h-11 flex-none rounded-md border-0 px-2.5 py-1.5 text-[13px] data-[state=active]:shadow-none md:min-h-8"
              >
                {label}
              </TabsTrigger>
            ))}
          </TabsList>
        </div>
        <div
          role="progressbar"
          aria-label="Tasks done"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={percent}
          className="bg-border h-1.5 rounded-full"
        >
          <div
            className="bg-primary h-1.5 rounded-full"
            style={{ width: `${percent}%` }}
          />
        </div>

        <TabsContent value="tasks" className="flex flex-col gap-[18px]">
          <AddTask projectId={project.id} />
          <TaskGroups tasks={tasks} links={links} titles={titles} />
        </TabsContent>
        <TabsContent value="evidence">
          <p
            className="text-muted-foreground text-sm"
            data-testid="evidence-not-set-up"
          >
            Evidence is not set up yet. When it is, each task shows what was
            observed (a commit, a session&apos;s activity) apart from what was
            reported (an agent&apos;s own to-do list), and neither changes your
            plan.
          </p>
        </TabsContent>
        <TabsContent value="decisions">
          <Decisions projectId={project.id} notes={notes} />
        </TabsContent>
        <TabsContent value="chats">
          {chats.length === 0 ? (
            <p className="text-muted-foreground text-sm">
              No chats attached. Attach one from a chat&apos;s header.
            </p>
          ) : (
            <ul className="flex flex-col">
              {chats.map((c) => (
                <li key={c.id} className="border-border border-t py-2.5">
                  <Link
                    href={`/workspace/chats/${c.to_ref}`}
                    className="text-primary underline underline-offset-2"
                  >
                    {chatTitle(titles.get(c.to_ref), c.label)}
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}

function chatTitle(title?: string, label?: string | null): string {
  if (title) return title;
  if (label) return label;
  return "Untitled chat";
}

function AddTask({ projectId }: { projectId: string }) {
  const [title, setTitle] = useState("");
  const add = useLedgerWrite((t: string) =>
    createTask(projectId, { title: t }),
  );
  return (
    <form
      className="bg-card border-border-strong flex flex-wrap items-center gap-2 rounded-xl border px-2.5 py-2"
      onSubmit={(e) => {
        e.preventDefault();
        const t = title.trim();
        if (!t) return;
        add.mutate(t, {
          onSuccess: () => setTitle(""),
          onError: onWriteError,
        });
      }}
    >
      <label className="min-w-0 flex-[1_1_360px]">
        <span className="sr-only">Add a task</span>
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Add a task, and press Enter"
          className="placeholder:text-muted-foreground w-full bg-transparent px-1 py-1 outline-none"
          data-testid="add-task"
        />
      </label>
    </form>
  );
}

function TaskGroups({
  tasks,
  links,
  titles,
}: {
  tasks: Task[];
  links: LedgerLink[];
  titles: Map<string, string>;
}) {
  const { groups, doneEarlier } = groupTasks(tasks);
  if (groups.length === 0) {
    return (
      <p className="text-muted-foreground text-sm" data-testid="no-tasks">
        No tasks yet.
      </p>
    );
  }
  return (
    <>
      {groups.map((group) => (
        <section
          key={group.key}
          aria-labelledby={`g-${group.key}`}
          className="flex flex-col"
          data-testid={`group-${group.key}`}
        >
          <h3
            id={`g-${group.key}`}
            className="text-muted-foreground mb-1.5 text-xs font-semibold"
          >
            {group.label}
          </h3>
          {group.tasks.map((task) => (
            <TaskRow
              key={task.id}
              task={task}
              origin={originOf(task, links, titles)}
            />
          ))}
        </section>
      ))}
      {doneEarlier > 0 && (
        <p className="text-muted-foreground text-xs">
          {doneEarlier} done before this week.
        </p>
      )}
    </>
  );
}

/** Where a task came from, when the ledger records it: the chat it was
 * promoted or captured from. A fact about the plan, not evidence. */
function originOf(
  task: Task,
  links: LedgerLink[],
  titles: Map<string, string>,
): string | null {
  const link = links.find(
    (l) =>
      l.from_kind === "task" && l.from_id === task.id && l.to_kind === "thread",
  );
  if (!link) return null;
  const title = titles.get(link.to_ref);
  return title ? `Added from chat “${title}”` : "Added from a chat";
}

function TaskRow({ task, origin }: { task: Task; origin: string | null }) {
  const toggle = useLedgerWrite(patchTask.bind(null, task.id));
  const done = task.status === "done";
  const owner = ownerWords(task.owner);
  const status = statusWords(task);
  const due = dueWords(task);
  return (
    <div
      className={cn(
        "border-border flex flex-wrap items-start gap-3 border-t px-1 py-3",
        done && "text-muted-foreground",
      )}
      data-testid="task"
      data-status={task.status}
    >
      <input
        type="checkbox"
        checked={done}
        disabled={toggle.isPending}
        aria-label={done ? `${task.title}, done` : `Mark ${task.title} as done`}
        onChange={() =>
          toggle.mutate(
            { version: task.version, status: done ? "todo" : "done" },
            { onError: onWriteError },
          )
        }
        className="accent-primary mt-0.5 size-[18px] shrink-0"
      />
      <div className="min-w-0 flex-[1_1_320px]">
        <div className={cn(done && "line-through")}>{task.title}</div>
        <div className="text-muted-foreground text-xs">
          {origin ?? "Evidence: not set up yet"}
        </div>
      </div>
      {owner && (
        <span
          className="border-border-strong text-foreground-2 flex items-center gap-1.5 rounded-md border py-0.5 pr-2 pl-0.5 text-xs"
          data-testid="owner"
        >
          {owner.source ? (
            <BrandLogo source={owner.source} name={owner.label} size={18} />
          ) : (
            <span className="pl-1.5" />
          )}
          {owner.label}
        </span>
      )}
      {status && (
        <span className={cn("text-xs", TONE[status.tone])}>{status.text}</span>
      )}
      {!done && !status && (
        <span
          className={cn(
            "text-xs",
            due.overdue ? "text-destructive" : "text-foreground-2",
          )}
          data-testid="due"
        >
          {due.text}
        </span>
      )}
    </div>
  );
}

function Decisions({
  projectId,
  notes,
}: {
  projectId: string;
  notes: ProjectView["notes"];
}) {
  const [decided, setDecided] = useState("");
  const add = useLedgerWrite((d: string) =>
    createNote(projectId, { decided: d }),
  );
  return (
    <div className="flex flex-col gap-3">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          const d = decided.trim();
          if (d)
            add.mutate(d, {
              onSuccess: () => setDecided(""),
              onError: onWriteError,
            });
        }}
      >
        <label className="block">
          <span className="sr-only">Record a decision</span>
          <input
            value={decided}
            onChange={(e) => setDecided(e.target.value)}
            placeholder="Record a decision, and press Enter"
            className="bg-card border-border-strong placeholder:text-muted-foreground w-full rounded-xl border px-3 py-2 outline-none"
          />
        </label>
      </form>
      {notes.length === 0 ? (
        <p className="text-muted-foreground text-sm">No decisions yet.</p>
      ) : (
        <ul className="flex flex-col">
          {notes.map((n) => (
            <li key={n.id} className="border-border border-t py-2.5">
              <div>{n.decided}</div>
              {n.why && (
                <div className="text-muted-foreground text-xs">{n.why}</div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Every open task across projects, each named with its project. */
function AllOpenTasks({
  projects,
  onOpen,
}: {
  projects: ProjectSummary[];
  onOpen: (id: string) => void;
}) {
  const withOpen = projects.filter((p) => p.open_tasks > 0);
  const results = useQueries({
    queries: withOpen.map((p) => ({
      queryKey: ["ledger", "project", p.id],
      queryFn: () => loadProject(p.id),
    })),
  });
  const failed = results
    .map((r, i) => (r.error ? withOpen[i]!.name : null))
    .filter(Boolean);
  return (
    <div className="flex flex-col gap-[18px]" data-testid="all-open-tasks">
      <h2 className="text-xl font-semibold">All open tasks</h2>
      {failed.length > 0 && (
        <p className="text-destructive text-sm" role="alert">
          {`I can't read: ${failed.join(", ")}. Their tasks are not shown.`}
        </p>
      )}
      {withOpen.length === 0 && (
        <p className="text-muted-foreground text-sm">No open tasks.</p>
      )}
      {results.map((r, i) =>
        r.data ? (
          <section key={withOpen[i]!.id} className="flex flex-col">
            <h3 className="text-muted-foreground mb-1.5 text-xs font-semibold">
              <button
                type="button"
                className="hover:text-foreground"
                onClick={() => onOpen(withOpen[i]!.id)}
              >
                {withOpen[i]!.name}
              </button>
            </h3>
            {r.data.tasks
              .filter((t) => t.status !== "done" && t.status !== "dropped")
              .map((t) => (
                <TaskRow key={t.id} task={t} origin={null} />
              ))}
          </section>
        ) : r.isLoading ? (
          <Skeleton key={withOpen[i]!.id} className="h-16" />
        ) : null,
      )}
    </div>
  );
}
