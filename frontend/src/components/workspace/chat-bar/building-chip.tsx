"use client";

import { HammerIcon, XIcon } from "lucide-react";

import type { Building } from "@/core/builder/api";
import { useBuilding, useDropBuilding } from "@/core/builder/hooks";
import { cn } from "@/lib/utils";

const KIND_WORD: Record<string, string> = {
  agent: "agent",
  skill: "skill",
  automation: "automation",
};

/**
 * "Building: <name>" above the chat bar (Spec 010 FR-003, FR-004): shown
 * while this chat has a build open, which starts when the assistant calls a
 * builder tool. × drops the draft: nothing is saved, nothing in the config
 * store changes, and later messages are ordinary chat.
 *
 * Graphite tokens only: the selected-thing fill (`bg-primary-subtle`) with
 * `text-foreground` on it (never muted: muted on primary-subtle fails AA in
 * dark, specs/006-workspace-studio/tokens.md).
 */
export function BuildingChipView({
  building,
  onDrop,
  dropping = false,
  className,
}: {
  building: Building;
  onDrop: () => void;
  dropping?: boolean;
  className?: string;
}) {
  const kind = KIND_WORD[building.kind] ?? "draft";
  return (
    <div
      role="status"
      aria-live="polite"
      data-testid="building-chip"
      className={cn(
        "bg-primary-subtle text-foreground border-primary/35 inline-flex h-[34px] max-w-full items-center gap-2 rounded-[17px] border pr-1 pl-3 text-sm",
        className,
      )}
    >
      <HammerIcon aria-hidden="true" className="text-primary size-4 shrink-0" />
      <span className="min-w-0 truncate">
        <span className="font-medium">Building:</span>{" "}
        <span title={`${building.title} (${kind})`}>{building.title}</span>
        {building.saved_version != null && (
          <span data-testid="building-saved">
            {" "}
            · saved as version {building.saved_version}
          </span>
        )}
      </span>
      <button
        type="button"
        onClick={onDrop}
        disabled={dropping}
        aria-label={`Stop building ${building.title} and drop the draft`}
        title="Drop the draft (nothing is saved)"
        data-testid="building-chip-drop"
        className="text-foreground hover:bg-surface-raised focus-visible:ring-ring inline-flex size-7 shrink-0 items-center justify-center rounded-full outline-none focus-visible:ring-2 disabled:opacity-50"
      >
        <XIcon aria-hidden="true" className="size-4" />
      </button>
    </div>
  );
}

/** The chip for a chat, or nothing when it is not building. */
export function BuildingChip({
  threadId,
  enabled,
  running,
  rowClassName,
}: {
  threadId: string;
  enabled: boolean;
  running: boolean;
  /** The row it sits in, rendered only while there is a build. */
  rowClassName?: string;
}) {
  const building = useBuilding(threadId, enabled, running);
  const drop = useDropBuilding(threadId);
  if (!enabled || !building) return null;
  return (
    <div className={rowClassName}>
      <BuildingChipView
        building={building}
        dropping={drop.isPending}
        onDrop={() => drop.mutate()}
      />
    </div>
  );
}
