"use client";

import { ListTodoIcon, Undo2Icon } from "lucide-react";
import { useState } from "react";

import { ChainOfThoughtStep } from "@/components/ai-elements/chain-of-thought";
import { Button } from "@/components/ui/button";
import { safeField } from "@/core/display/safe";
import { LedgerError, parseLedgerResult, undoWrite } from "@/core/ledger/api";

/**
 * A ledger write the assistant made without asking (a routine task or note
 * change that followed from your own message: 005 FR-009 Amendment 1), as
 * disclosed in the chat, with an Undo that reverts it in the ledger. A write
 * that was confirmed, or a suggestion still waiting on its card, has no Undo.
 */
export function LedgerWriteStep({
  label,
  result,
}: {
  label: React.ReactNode;
  result: string;
}) {
  const parsed = parseLedgerResult(result);
  const text = safeField(parsed.text);
  const writeId = parsed.writeId;
  const [state, setState] = useState<
    | { kind: "idle" }
    | { kind: "busy" }
    | { kind: "done" }
    | { kind: "failed"; why: string }
  >({ kind: "idle" });

  async function undo() {
    if (!writeId) return;
    setState({ kind: "busy" });
    try {
      await undoWrite(writeId);
      setState({ kind: "done" });
    } catch (e) {
      setState({
        kind: "failed",
        why: e instanceof LedgerError ? e.message : String(e),
      });
    }
  }

  return (
    <ChainOfThoughtStep
      label={label}
      icon={ListTodoIcon}
      description={
        <span className="flex flex-wrap items-center gap-2">
          <span>{text}</span>
          {writeId && state.kind !== "done" ? (
            <Button
              variant="outline"
              size="sm"
              disabled={state.kind === "busy"}
              onClick={() => void undo()}
              data-testid="ledger-undo"
            >
              <Undo2Icon className="size-3.5" aria-hidden />
              Undo
            </Button>
          ) : null}
          {state.kind === "done" ? (
            <span role="status" data-testid="ledger-undone">
              Undone.
            </span>
          ) : null}
          {state.kind === "failed" ? (
            <span role="alert" className="text-destructive">
              Not undone: {state.why}
            </span>
          ) : null}
        </span>
      }
    />
  );
}
