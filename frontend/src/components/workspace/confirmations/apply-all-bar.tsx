"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { applyAll } from "@/core/confirmations/api";
import { PENDING_CONFIRMATIONS_KEY } from "@/core/confirmations/hooks";
import type { PendingAction } from "@/core/confirmations/types";
import { LedgerError, undoWrite } from "@/core/ledger/api";

/**
 * "Apply all" for a group of routine ledger suggestions (005 FR-009
 * Amendment 1): one click confirms them together as ONE batch, and one Undo
 * reverts the batch. Tier 3 cards are never suggestions, so they never join.
 */
export function ApplyAllBar({ actions }: { actions: PendingAction[] }) {
  const queryClient = useQueryClient();
  const suggestions = actions.filter((a) => a.suggestion);
  const [state, setState] = useState<
    | { kind: "idle" }
    | { kind: "busy" }
    | { kind: "applied"; writeId: string | null; count: number }
    | { kind: "undone" }
    | { kind: "failed"; why: string }
  >({ kind: "idle" });

  if (suggestions.length < 2 && state.kind === "idle") return null;

  async function apply() {
    setState({ kind: "busy" });
    try {
      const out = await applyAll(suggestions.map((a) => a.id));
      setState({
        kind: "applied",
        writeId: out.write_id,
        count: out.results.filter((r) => r.outcome === "executed").length,
      });
    } catch (e) {
      setState({
        kind: "failed",
        why: e instanceof Error ? e.message : String(e),
      });
    }
    void queryClient.invalidateQueries({ queryKey: PENDING_CONFIRMATIONS_KEY });
  }

  async function undo(writeId: string) {
    try {
      await undoWrite(writeId);
      setState({ kind: "undone" });
    } catch (e) {
      setState({
        kind: "failed",
        why: e instanceof LedgerError ? e.message : String(e),
      });
    }
  }

  return (
    <div
      className="border-border bg-card flex flex-wrap items-center gap-2 rounded-lg border px-3 py-2 text-sm"
      data-testid="apply-all"
    >
      {state.kind === "idle" || state.kind === "busy" ? (
        <>
          <span className="text-foreground-2">
            {suggestions.length} suggestions from what I read
          </span>
          <Button
            size="sm"
            variant="outline"
            disabled={state.kind === "busy"}
            onClick={() => void apply()}
            data-testid="apply-all-button"
          >
            Apply all {suggestions.length}
          </Button>
        </>
      ) : null}
      {state.kind === "applied" ? (
        <>
          <span role="status">Applied {state.count} together.</span>
          {state.writeId ? (
            <Button
              size="sm"
              variant="outline"
              onClick={() => void undo(state.writeId!)}
              data-testid="apply-all-undo"
            >
              Undo all
            </Button>
          ) : null}
        </>
      ) : null}
      {state.kind === "undone" ? <span role="status">Undone.</span> : null}
      {state.kind === "failed" ? (
        <span role="alert" className="text-destructive">
          Not done: {state.why}
        </span>
      ) : null}
    </div>
  );
}
