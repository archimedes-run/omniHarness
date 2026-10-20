/** Mirrors app/gateway/routers/ledger.py and persistence/ledger/model.py. */
export type ProjectStatus = "active" | "paused" | "done" | "archived";
export type TaskStatus = "todo" | "doing" | "blocked" | "done" | "dropped";

export interface Project {
  id: string;
  name: string;
  why: string | null;
  status: ProjectStatus;
  context: string | null;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface ProjectSummary extends Project {
  open_tasks: number;
  overdue: number;
  done_tasks: number;
}

export interface Goal {
  id: string;
  project_id: string;
  title: string;
  definition_of_done: string;
  target_date: string | null;
  version: number;
  progress: { done: number; total: number };
}

export interface Owner {
  kind: "user" | "agent" | "session" | "workflow";
  ref: string | null;
}

export interface Task {
  id: string;
  project_id: string;
  short_id: string;
  title: string;
  status: TaskStatus;
  owner: Owner | null;
  due_date: string | null;
  goal_id: string | null;
  version: number;
  done_at: string | null;
}

export interface Note {
  id: string;
  decided: string;
  why: string | null;
  thread_id: string | null;
  created_at: string;
}

export interface Link {
  id: string;
  from_kind: "project" | "task";
  from_id: string;
  to_kind: "thread" | "workflow" | "session" | "repository" | "external";
  to_ref: string;
  label: string | null;
}

export interface ProjectView {
  project: Project;
  goals: Goal[];
  tasks: Task[];
  notes: Note[];
  links: Link[];
}
