"use client";

import Link from "next/link";

import { dueLabel, taskProgress } from "@/core/home/logic";
import { useProjects } from "@/core/ledger/hooks";
import type { ProjectSummary } from "@/core/ledger/types";

import { CantTell, Empty, HomeCard, Loading } from "./home-card";

const SHOWN = 4;

/**
 * Projects (Main board), from the Project Ledger's summaries: the same query
 * the Projects page reads. "N of M tasks" with a bar, a subtitle (why the
 * project exists, its next due date, anything overdue), or "No task list yet".
 */
export function ProjectsCard() {
  const { projects, error, isLoading } = useProjects();
  const open = projects?.filter(
    (p) => p.status === "active" || p.status === "paused",
  );
  return (
    <HomeCard
      id="projects"
      title="Projects"
      testId="home-projects"
      className="gap-3.5"
      action={
        <Link
          href="/workspace/projects"
          className="text-primary text-xs underline-offset-4 hover:underline"
        >
          All projects
        </Link>
      }
    >
      {isLoading && <Loading />}
      {error != null && (
        <CantTell testId="home-projects-unreadable">
          {`Can't read your projects: ${error instanceof Error ? error.message : String(error)}.`}
        </CantTell>
      )}
      {open?.length === 0 && (
        <Empty testId="home-projects-empty">
          No open projects.{" "}
          <Link
            href="/workspace/projects"
            className="text-primary underline-offset-4 hover:underline"
          >
            Start one
          </Link>
        </Empty>
      )}
      {open?.slice(0, SHOWN).map((p) => (
        <ProjectRow key={p.id} project={p} />
      ))}
      {open && open.length > SHOWN && (
        <p className="text-muted-foreground text-xs">
          {`and ${open.length - SHOWN} more`}
        </p>
      )}
    </HomeCard>
  );
}

function ProjectRow({ project }: { project: ProjectSummary }) {
  const progress = taskProgress(project);
  const subtitle = [
    project.why?.split("\n")[0]?.trim(),
    project.status === "paused" ? "Paused" : null,
    project.overdue > 0 ? `${project.overdue} overdue` : null,
    project.next_due ? dueLabel(project.next_due) : null,
  ].filter(Boolean);
  return (
    <div data-testid="home-project">
      <div className="flex justify-between gap-3">
        <Link
          href={`/workspace/projects/${project.id}`}
          className="text-foreground truncate text-sm font-medium hover:underline"
        >
          {project.name}
        </Link>
        <span
          className="text-muted-foreground shrink-0 text-xs"
          data-testid="home-project-progress"
        >
          {progress ? progress.label : "No task list yet"}
        </span>
      </div>
      {subtitle.length > 0 && (
        <p className="text-muted-foreground mt-0.5 truncate text-xs">
          {subtitle.join(" · ")}
        </p>
      )}
      {progress && (
        <div
          className="bg-border mt-2 h-1.5 rounded-full"
          role="progressbar"
          aria-label={`${project.name}: ${progress.label} done`}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={progress.percent}
        >
          <div
            className="bg-primary h-1.5 rounded-full"
            style={{ width: `${progress.percent}%` }}
          />
        </div>
      )}
    </div>
  );
}
