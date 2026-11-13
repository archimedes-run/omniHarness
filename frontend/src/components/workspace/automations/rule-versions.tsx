"use client";

import { RotateCcwIcon, Trash2Icon } from "lucide-react";
import { useState } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { RuleEditError } from "@/core/automations/api";
import { useRuleVersions, useUndoRule } from "@/core/automations/hooks";
import {
  deletedUndo,
  restoreError,
  versionRows,
  type VersionAction,
} from "@/core/automations/versions";
import { cn } from "@/lib/utils";

/**
 * One automation's versions (Spec 010 Slice 1): every change made on this
 * page, in Studio or (later) in chat, and every hand edit of the rules file,
 * newest first. "Undo" on the latest change and "Restore this version" on an
 * older one each write a NEW version through the one store; a stale one is
 * refused and the list reloads.
 */
export function RuleVersionsList({
  ruleId,
  via,
  writable = true,
  locked,
  onRestored,
  className,
}: {
  ruleId: string;
  via: "page" | "studio";
  writable?: boolean;
  /** Why restoring is off right now (e.g. unsaved edits in Studio). */
  locked?: string;
  onRestored?: () => void;
  className?: string;
}) {
  const { data, error, isLoading, refetch } = useRuleVersions(ruleId);
  const undo = useUndoRule();
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(
    null,
  );

  async function run(action: VersionAction) {
    if (!data) return;
    setMessage(null);
    try {
      await undo.mutateAsync({
        id: ruleId,
        toVersion: action.toVersion,
        baseVersion: data.current,
        via,
      });
      setMessage({
        ok: true,
        text:
          action.toVersion === 0
            ? "Undone: the automation is deleted, as a new version."
            : `Restored version ${action.toVersion} as a new version.`,
      });
      onRestored?.();
    } catch (e) {
      const status = e instanceof RuleEditError ? e.status : 0;
      setMessage({
        ok: false,
        text: restoreError(status, e instanceof Error ? e.message : String(e)),
      });
      if (status === 409) void refetch();
    }
  }

  if (isLoading) return <Skeleton className="h-24 rounded-lg" />;
  if (error) {
    const status = error instanceof RuleEditError ? error.status : 0;
    return (
      <p
        className="text-muted-foreground text-sm"
        data-testid="rule-versions-none"
      >
        {status === 404
          ? "No versions yet."
          : `I cannot read its versions: ${error.message}`}
      </p>
    );
  }
  if (!data) return null;
  const gone = deletedUndo(data);
  // A deleted rule's Undo is the banner's: one button, not two, for it.
  const rows = versionRows(data).map((row, i) =>
    gone && i === 0 ? { ...row, action: null } : row,
  );
  const canAct = writable && !locked && !undo.isPending;

  return (
    <div
      className={cn("flex flex-col gap-3", className)}
      data-testid="rule-versions"
    >
      {gone && (
        <div
          className="border-border bg-card flex flex-wrap items-center gap-3 rounded-lg border px-3.5 py-3"
          role="status"
          data-testid="rule-deleted"
        >
          <Trash2Icon size={16} aria-hidden className="text-muted-foreground" />
          <span className="min-w-0 flex-1 text-sm">
            Deleted. Undo brings back version {gone.toVersion}, as a new
            version.
          </span>
          <Button
            size="sm"
            variant="outline"
            disabled={!canAct}
            onClick={() => void run(gone)}
            data-testid="rule-deleted-undo"
          >
            <RotateCcwIcon aria-hidden />
            Undo
          </Button>
        </div>
      )}
      {locked && (
        <p
          className="text-muted-foreground text-xs"
          data-testid="rule-versions-locked"
        >
          {locked}
        </p>
      )}
      {message && (
        <p
          className={cn(
            "text-sm",
            message.ok ? "text-foreground" : "text-destructive",
          )}
          role={message.ok ? "status" : "alert"}
          data-testid={message.ok ? "rule-restored" : "rule-restore-error"}
        >
          {message.text}
        </p>
      )}
      {rows.length === 0 ? (
        <p
          className="text-muted-foreground text-sm"
          data-testid="rule-versions-none"
        >
          No changes recorded yet. The first change records how it is now, so it
          can be undone.
        </p>
      ) : (
        <ul aria-label="Versions">
          {rows.map((row) => (
            <li
              key={row.key}
              className="border-border flex flex-wrap items-center gap-x-3 gap-y-1 border-t py-3 first:border-t-0"
              data-testid="rule-version"
              data-version={row.label}
            >
              <span className="text-muted-foreground w-9 shrink-0 text-xs tabular-nums">
                {row.label}
              </span>
              <span className="flex min-w-0 flex-[1_1_240px] flex-col">
                <span className="text-sm">
                  <span className="font-medium">{row.source}</span>
                  {row.current && (
                    <span className="text-muted-foreground"> · current</span>
                  )}
                </span>
                <span className="text-muted-foreground text-xs">
                  {row.at}
                  {row.at ? " · " : ""}
                  {row.changed}
                </span>
              </span>
              {row.action && (
                <Button
                  size="sm"
                  variant={row.action.kind === "undo" ? "outline" : "ghost"}
                  disabled={!canAct}
                  onClick={() => row.action && void run(row.action)}
                  data-testid={
                    row.action.kind === "undo"
                      ? "rule-version-undo"
                      : "rule-version-restore"
                  }
                >
                  {row.action.kind === "undo" ? (
                    <>
                      <RotateCcwIcon aria-hidden />
                      Undo
                    </>
                  ) : (
                    "Restore this version"
                  )}
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** For a rule the board no longer lists: its versions, with the deleted
 * state's Undo, or the "no such automation" note when it never had any. */
export function MissingRule({
  ruleId,
  writable,
}: {
  ruleId: string;
  writable: boolean;
}) {
  const { data, error } = useRuleVersions(ruleId);
  if (data && !data.exists) {
    return (
      <div className="flex max-w-[760px] flex-col gap-4 px-4 py-5 md:px-7">
        <h2 className="text-lg font-semibold">{ruleId}</h2>
        <RuleVersionsList ruleId={ruleId} via="page" writable={writable} />
      </div>
    );
  }
  return (
    <div className="px-4 py-5 md:px-7">
      <Alert data-testid="no-such-rule">
        <AlertTitle>There is no automation called {ruleId}</AlertTitle>
        <AlertDescription>
          {error || !data
            ? "It may have been deleted or renamed."
            : "It may have been renamed."}
        </AlertDescription>
      </Alert>
    </div>
  );
}
