"use client";

import { FolderPlusIcon, XIcon } from "lucide-react";
import Link from "next/link";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { attachThread, detachLink } from "@/core/ledger/api";
import {
  useLedgerWrite,
  useProjects,
  useThreadProjects,
} from "@/core/ledger/hooks";

/** The projects this conversation is attached to, in its header (FR-011). */
export function ThreadProjects({
  threadId,
  title,
}: {
  threadId: string;
  title?: string;
}) {
  const attached = useThreadProjects(threadId);
  const { projects } = useProjects();
  const attach = useLedgerWrite((projectId: string) =>
    attachThread(projectId, threadId, title),
  );
  const detach = useLedgerWrite(detachLink);
  const ids = new Set((attached ?? []).map((a) => a.project.id));
  const choices = (projects ?? []).filter(
    (p) => !ids.has(p.id) && p.status !== "archived",
  );

  return (
    <div className="flex items-center gap-1" data-testid="thread-projects">
      {(attached ?? []).map(({ link_id, project }) => (
        <span
          key={link_id}
          className="text-muted-foreground group hover:text-foreground flex items-center gap-0.5 text-xs"
          data-testid="thread-project"
        >
          <Link href={`/workspace/projects/${project.id}`}>{project.name}</Link>
          <button
            type="button"
            aria-label={`Detach from ${project.name}`}
            className="opacity-0 group-hover:opacity-100 focus-visible:opacity-100"
            onClick={() => detach.mutate(link_id)}
          >
            <XIcon className="size-3" />
          </button>
        </span>
      ))}
      {choices.length > 0 && (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="sm"
              className="text-muted-foreground"
              aria-label="Add to project"
            >
              <FolderPlusIcon />
              {(attached ?? []).length === 0 && "Add to project"}
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuLabel className="text-muted-foreground text-xs font-normal">
              Attach this chat to
            </DropdownMenuLabel>
            {choices.map((project) => (
              <DropdownMenuItem
                key={project.id}
                onSelect={() =>
                  attach.mutate(project.id, {
                    onSuccess: () => toast(`Attached to ${project.name}`),
                    onError: (e) => toast.error(e.message),
                  })
                }
              >
                {project.name}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      )}
    </div>
  );
}
