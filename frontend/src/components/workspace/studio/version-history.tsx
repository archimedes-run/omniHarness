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

import { useStudioCopy } from "./copy";
import { useStudio } from "./studio";

/**
 * Every change to an agent or skill is a version in the one store; Restore
 * makes an earlier one the next version, refused when it changed meanwhile.
 * Kept from the previous Studio as one small button beside the owner badge
 * (the board has no place for it; the save toast's Undo covers the common
 * case).
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
  const h = useStudioCopy().history;
  const studio = useStudio();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
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
      studio.toast(
        kind === "agent" ? h.restoredAgent(version) : h.restored(version),
      );
      await queryClient.invalidateQueries({ queryKey: key });
      onRestored();
    } catch (e) {
      const status = (e as { status?: number }).status;
      studio.toast(
        status === 409
          ? h.stale
          : h.failed(e instanceof Error ? e.message : String(e)),
      );
    }
  }

  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      <DropdownMenuTrigger
        className="btn sm ghost"
        data-testid="studio-history"
      >
        <HistoryIcon size={14} aria-hidden />
        {h.button}
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="end"
        className="max-h-80 w-80"
        data-testid="studio-history-menu"
      >
        <DropdownMenuLabel>{h.title}</DropdownMenuLabel>
        {kind === "agent" ? (
          <p className="text-muted-foreground px-2 pb-1.5 text-xs">
            {h.grantsKept}
          </p>
        ) : null}
        <DropdownMenuSeparator />
        {error ? (
          <DropdownMenuItem disabled>
            {h.unreadable(String(error.message))}
          </DropdownMenuItem>
        ) : data?.versions.length === 0 ? (
          <DropdownMenuItem disabled>{h.none}</DropdownMenuItem>
        ) : (
          (data?.versions ?? []).map((v) => {
            const current = v.version === data?.current;
            const what = v.deleted
              ? h.deleted
              : (h.source[v.source] ?? v.source);
            return (
              <DropdownMenuItem
                key={v.version}
                disabled={current}
                onSelect={() => void restore(v.version)}
                className="flex flex-col items-start gap-0.5"
                data-testid="studio-version"
              >
                <span className="flex w-full justify-between gap-2">
                  <span className="font-medium">{`v${v.version} · ${h.who(v.who)} ${what}`}</span>
                  <span className="text-muted-foreground text-xs">
                    {current ? h.current : h.restore}
                  </span>
                </span>
                <span className="text-muted-foreground text-xs">
                  {v.at ? new Date(v.at).toLocaleString() : ""}
                  {v.changed.length ? ` · ${v.changed.join(", ")}` : ""}
                </span>
              </DropdownMenuItem>
            );
          })
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
