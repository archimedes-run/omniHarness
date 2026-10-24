"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { safeField } from "@/core/display/safe";
import {
  loadRunSummary,
  RunSummaryError,
  undoRun,
  type RunSummary,
} from "@/core/studio/run-summary";

/**
 * A scheduled run's summary (Feature 006): each change it made on its own
 * under a standing grant, with what it came from, and "Undo all for this
 * run". The Telegram message links here; nothing in the channel acts.
 */
export function RunSummaryView({ firingId }: { firingId: string }) {
  const queryClient = useQueryClient();
  const key = ["studio", "run", firingId];
  const { data, error, isLoading } = useQuery({
    queryKey: key,
    queryFn: () => loadRunSummary(firingId),
    retry: false,
  });
  const [note, setNote] = useState<{ text: string; bad: boolean } | null>(null);
  const [busy, setBusy] = useState(false);

  async function undoAll() {
    setBusy(true);
    try {
      const next = await undoRun(firingId);
      queryClient.setQueryData<RunSummary>(key, next);
      setNote({ text: "Undone: every change this run made.", bad: false });
    } catch (e) {
      setNote({
        text: `Not undone: ${e instanceof Error ? e.message : String(e)}`,
        bad: true,
      });
    } finally {
      setBusy(false);
    }
  }

  if (isLoading) return <p className="text-muted-foreground">Loading…</p>;
  if (error) {
    const status = error instanceof RunSummaryError ? error.status : 0;
    return (
      <p role="alert" className="text-destructive">
        {status === 404
          ? "This run did nothing on its own, or it is not yours."
          : `Can't tell what this run did: ${error.message}`}
      </p>
    );
  }
  if (!data) return null;

  return (
    <section className="flex flex-col gap-4" data-testid="run-summary">
      <header className="flex flex-col gap-1">
        <h1 className="text-xl font-semibold">Done on its own in this run</h1>
        <p className="text-muted-foreground text-sm">
          {data.agent === "lead_agent" ? "Lead agent" : data.agent}
          {data.rule_id ? ` · automation ${data.rule_id}` : ""} · under its
          standing grants
        </p>
      </header>
      <ul className="border-border bg-card divide-border divide-y rounded-lg border">
        {data.writes.map((write, index) => (
          <li
            key={write.write_id ?? index}
            className="flex flex-col gap-0.5 px-4 py-3"
            data-testid="run-write"
          >
            <span className={write.undone ? "line-through" : undefined}>
              {safeField(write.targets.join("; ")) || write.tool}
            </span>
            <span className="text-muted-foreground text-sm">
              {safeField(write.source_label)}
              {write.undone ? " · undone" : ""}
            </span>
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap items-center gap-3">
        {data.all_undone ? (
          <span
            className="text-muted-foreground text-sm"
            data-testid="all-undone"
          >
            Everything this run did has been undone.
          </span>
        ) : (
          <Button
            variant="outline"
            disabled={busy}
            onClick={() => void undoAll()}
            data-testid="undo-run"
          >
            Undo all for this run
          </Button>
        )}
        {note ? (
          <span
            role={note.bad ? "alert" : "status"}
            className={note.bad ? "text-destructive text-sm" : "text-sm"}
            data-testid="undo-run-note"
          >
            {note.text}
          </span>
        ) : null}
      </div>
    </section>
  );
}
