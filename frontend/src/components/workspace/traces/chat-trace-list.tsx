"use client";

import Link from "next/link";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { RowList } from "@/components/workspace/page-kit";
import { useChatTraces } from "@/core/traces";
import { traceHref } from "@/core/verification";

import { StatusChip } from "./trace-view";

function when(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
}

/**
 * Chat runs in the run history (spec 009 FR-080, kind "chat"), each linking
 * to its trace. Shown in Settings → Activity log beside the automation runs.
 */
export function ChatTraceList({
  threadId,
  limit = 20,
}: {
  threadId?: string;
  limit?: number;
}) {
  const { traces, error, isLoading } = useChatTraces(threadId, limit);
  return (
    <section
      className="space-y-3"
      aria-labelledby="chat-traces-heading"
      data-testid="chat-traces"
    >
      <h2 id="chat-traces-heading" className="text-[15px] font-semibold">
        Chat run traces
      </h2>
      {isLoading && <p className="text-muted-foreground text-sm">Loading…</p>}
      {error && (
        <Alert variant="destructive">
          <AlertTitle>I cannot read the chat traces</AlertTitle>
          <AlertDescription>{String(error.message)}</AlertDescription>
        </Alert>
      )}
      {traces?.length === 0 && (
        <p className="text-muted-foreground text-sm">
          No chat run has been traced yet. Each chat run records its steps when
          it ends.
        </p>
      )}
      {traces && traces.length > 0 && (
        <RowList>
          {traces.map((run) => (
            <li
              key={run.id}
              className="flex flex-wrap items-center gap-3 px-4 py-2.5 text-sm"
            >
              <Link
                href={traceHref(run.source_id)}
                className="text-primary font-medium underline-offset-2 hover:underline"
              >
                Run of {when(run.started_at)}
              </Link>
              <StatusChip status={run.status} />
              {run.thread_id && (
                <Link
                  href={`/workspace/chats/${encodeURIComponent(run.thread_id)}`}
                  className="text-muted-foreground hover:text-foreground ml-auto text-xs underline-offset-2 hover:underline"
                >
                  Open chat
                </Link>
              )}
            </li>
          ))}
        </RowList>
      )}
    </section>
  );
}
