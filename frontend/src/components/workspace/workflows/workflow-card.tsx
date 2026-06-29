"use client";

import { PlayIcon } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { StatusBadge } from "@/components/workspace/status-badge";

import type { Workflow, WorkflowRun } from "./types";

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  if (diff < 60000) return "just now";
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
  return new Date(iso).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return iso;
  }
}

interface WorkflowCardProps {
  workflow: Workflow;
  lastRun?: WorkflowRun | null;
  onRun: () => void;
}

export function WorkflowCard({ workflow, lastRun, onRun }: WorkflowCardProps) {
  return (
    <Link
      href={`/workspace/workflows/${workflow.id}`}
      className="block focus:outline-none"
    >
      <Card className="hover:bg-muted/30 cursor-pointer gap-3 py-4 transition-colors">
        <CardHeader className="px-4 pb-0">
          <div className="flex items-start justify-between gap-2">
            <CardTitle className="truncate text-base font-medium">
              {workflow.title}
            </CardTitle>
            <StatusBadge status={workflow.status} />
          </div>
        </CardHeader>

        <CardContent className="px-4 pb-0">
          {workflow.description ? (
            <p className="text-muted-foreground line-clamp-2 text-sm">
              {workflow.description}
            </p>
          ) : null}

          <p className="text-muted-foreground mt-1.5 text-xs">
            Created {formatDate(workflow.created_at)}
          </p>

          {/* Phase 2: schedule */}
          <div />

          {lastRun ? (
            <div className="mt-1.5 flex items-center gap-1.5">
              <span className="text-muted-foreground text-xs">Last run:</span>
              <StatusBadge status={lastRun.status} />
              {lastRun.started_at ? (
                <span className="text-muted-foreground text-xs">
                  {timeAgo(lastRun.started_at)}
                </span>
              ) : null}
            </div>
          ) : null}

          {/* Phase 2: run count */}
          <div />
        </CardContent>

        <CardFooter className="px-4 pt-1 pb-0">
          <div className="flex w-full items-center justify-between">
            {/* Phase 2: activate toggle */}
            <div />

            <Button
              size="sm"
              variant="outline"
              className="gap-1.5"
              onClick={(e) => {
                e.preventDefault();
                e.stopPropagation();
                onRun();
              }}
            >
              <PlayIcon className="h-3.5 w-3.5" />
              Run
            </Button>
          </div>
        </CardFooter>
      </Card>
    </Link>
  );
}
