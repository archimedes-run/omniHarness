"use client";

import { PlusIcon } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { NewProjectDialog } from "@/components/workspace/ledger/new-project-dialog";
import { useProjects } from "@/core/ledger/hooks";
import { formatTimeAgo } from "@/core/utils/datetime";

/** Projects (Feature 005): the user's own source of truth for personal work. */
export default function ProjectsPage() {
  const { projects, error, isLoading } = useProjects();
  const [creating, setCreating] = useState(false);

  return (
    <div className="mx-auto w-full max-w-3xl space-y-5 p-6">
      <header className="flex items-start justify-between gap-4">
        <div className="space-y-1">
          <h1 className="text-xl font-semibold">Projects</h1>
          <p className="text-muted-foreground text-sm">
            What you are working toward, with its goals, tasks and decisions.
          </p>
        </div>
        <Button onClick={() => setCreating(true)}>
          <PlusIcon />
          New project
        </Button>
      </header>

      {error != null && (
        <p className="text-destructive text-sm" role="alert">
          {`I can't read your projects: ${error.message}`}
        </p>
      )}

      {isLoading && (
        <div className="space-y-2" data-testid="projects-loading">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-16 rounded-lg" />
          ))}
        </div>
      )}

      {projects?.length === 0 && (
        <div
          className="text-muted-foreground rounded-lg border border-dashed p-8 text-center text-sm"
          data-testid="projects-empty"
        >
          No projects yet. Tell the assistant what you&apos;re working on, or
          create one here.
        </div>
      )}

      {projects && projects.length > 0 && (
        <ul className="divide-border divide-y rounded-lg border">
          {projects.map((project) => (
            <li key={project.id} data-testid="project">
              <Link
                href={`/workspace/projects/${project.id}`}
                className="hover:bg-accent/50 flex items-start justify-between gap-4 px-4 py-3"
              >
                <div className="min-w-0 space-y-0.5">
                  <p className="text-foreground truncate font-medium">
                    {project.name}
                    {project.status !== "active" && (
                      <span className="text-muted-foreground ml-2 text-xs font-normal">
                        {project.status}
                      </span>
                    )}
                  </p>
                  {project.why && (
                    <p className="text-muted-foreground truncate text-sm">
                      {project.why}
                    </p>
                  )}
                </div>
                <div className="text-muted-foreground shrink-0 text-right text-xs">
                  <p data-testid="counts">
                    {`${project.open_tasks} open`}
                    {project.overdue > 0 && (
                      <span className="text-destructive">{` · ${project.overdue} overdue`}</span>
                    )}
                  </p>
                  <p>{`Updated ${formatTimeAgo(project.updated_at)}`}</p>
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}

      <NewProjectDialog open={creating} onOpenChange={setCreating} />
    </div>
  );
}
