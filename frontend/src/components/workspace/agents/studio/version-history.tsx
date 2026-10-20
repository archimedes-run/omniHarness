"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { HistoryIcon } from "lucide-react";
import { useState } from "react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { loadVersions, undoTo } from "@/core/studio";
import { cn } from "@/lib/utils";

import { useStudioCopy } from "./copy";
import { formatWhen } from "./runs";
import { outlineButton } from "./studio-frame";

/**
 * Version history with undo (user decision 2026-10-20): every change to an
 * agent or skill is a version in the one store; Restore makes an earlier one
 * the next version, and is refused when someone changed it meanwhile. The
 * board has no tab for it, so it is one small button in the footer.
 */
export function VersionHistory({
  kind,
  name,
  onRestored,
}: {
  kind: "agent" | "skill";
  name: string;
  onRestored: () => void;
}) {
  const c = useStudioCopy();
  const h = c.history;
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState<{ text: string; bad: boolean } | null>(null);
  const key = ["studio", "versions", kind, name];
  const { data, error } = useQuery({
    queryKey: key,
    queryFn: () => loadVersions(kind, name),
    enabled: open,
  });

  async function restore(version: number) {
    if (!data) return;
    try {
      await undoTo(kind, name, version, data.current);
      setNote({ text: h.restored(version), bad: false });
      void queryClient.invalidateQueries({ queryKey: key });
      onRestored();
    } catch (e) {
      const status = (e as { status?: number }).status;
      setNote({
        text:
          status === 409
            ? h.stale
            : h.failed(e instanceof Error ? e.message : String(e)),
        bad: true,
      });
    }
  }

  return (
    <div className="mr-auto flex flex-wrap items-center gap-2">
      <DropdownMenu open={open} onOpenChange={setOpen}>
        <DropdownMenuTrigger
          className={cn(outlineButton, "border-transparent px-3")}
          data-testid="studio-history"
        >
          <HistoryIcon className="size-4" aria-hidden />
          {h.button}
        </DropdownMenuTrigger>
        <DropdownMenuContent
          align="start"
          side="top"
          className="max-h-80 w-80"
          data-testid="studio-history-menu"
        >
          <DropdownMenuLabel>{h.title}</DropdownMenuLabel>
          <DropdownMenuSeparator />
          {error ? (
            <DropdownMenuItem disabled>
              {h.unreadable(String(error.message))}
            </DropdownMenuItem>
          ) : data?.versions.length === 0 ? (
            <DropdownMenuItem disabled>{h.none}</DropdownMenuItem>
          ) : (
            (data?.versions ?? []).map((v) => {
              const isCurrent = v.version === data?.current;
              const what = v.deleted
                ? h.deleted
                : (h.source[v.source] ?? v.source);
              const changed = v.changed.length
                ? ` · ${v.changed.join(", ")}`
                : "";
              return (
                <DropdownMenuItem
                  key={v.version}
                  disabled={isCurrent}
                  onSelect={() => void restore(v.version)}
                  className="flex flex-col items-start gap-0.5"
                  data-testid="studio-version"
                >
                  <span className="flex w-full justify-between gap-2">
                    <span className="font-medium">{`v${v.version} · ${h.who(v.who)} ${what}`}</span>
                    <span className="text-muted-foreground text-xs">
                      {isCurrent ? h.current : h.restore}
                    </span>
                  </span>
                  <span className="text-muted-foreground text-xs">
                    {v.at ? formatWhen(v.at, c.agents) : ""}
                    {changed}
                  </span>
                </DropdownMenuItem>
              );
            })
          )}
        </DropdownMenuContent>
      </DropdownMenu>
      {note ? (
        <span
          className={cn(
            "text-sm",
            note.bad ? "text-destructive" : "text-muted-foreground",
          )}
          role={note.bad ? "alert" : "status"}
          data-testid="studio-history-note"
        >
          {note.text}
        </span>
      ) : null}
    </div>
  );
}
