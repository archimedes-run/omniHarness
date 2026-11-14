"use client";

import { BrainIcon, XIcon } from "lucide-react";
import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

export const MEMORY_TOGGLE_LABEL = "Don't use memory in this chat";

/**
 * "Memory off in this chat" above the chat bar: shown while this chat does not
 * read the owner's memory or past chats (set by the composer toggle, or by the
 * server when the owner asked for it). × turns memory back on.
 *
 * Same tokens as the Building chip: `text-foreground` on `bg-primary-subtle`
 * (muted text on that fill fails AA in dark).
 */
export function MemoryOffChipView({
  onTurnOn,
  changing = false,
  className,
}: {
  onTurnOn: () => void;
  changing?: boolean;
  className?: string;
}) {
  return (
    <div
      role="status"
      aria-live="polite"
      data-testid="memory-off-chip"
      className={cn(
        "bg-primary-subtle text-foreground border-primary/35 inline-flex h-[34px] max-w-full items-center gap-2 rounded-[17px] border pr-1 pl-3 text-sm",
        className,
      )}
    >
      <BrainIcon aria-hidden="true" className="text-primary size-4 shrink-0" />
      <span className="min-w-0 truncate font-medium">
        Memory off in this chat
      </span>
      <button
        type="button"
        onClick={onTurnOn}
        disabled={changing}
        aria-label="Turn memory back on"
        title="Turn memory back on"
        data-testid="memory-off-chip-undo"
        className="text-foreground hover:bg-surface-raised focus-visible:ring-ring inline-flex size-7 shrink-0 items-center justify-center rounded-full outline-none focus-visible:ring-2 disabled:opacity-50"
      >
        <XIcon aria-hidden="true" className="size-4" />
      </button>
    </div>
  );
}

/**
 * The composer's memory switch, next to Attach: pressed means this chat does
 * not use memory. A real toggle button (aria-pressed) with its label as name.
 */
export function MemoryToggleView({
  memoryOff,
  onToggle,
  disabled = false,
  className,
  ...props
}: Omit<ComponentProps<"button">, "onToggle"> & {
  memoryOff: boolean;
  onToggle: (off: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <button
      // The tooltip's trigger props (pointer, focus, ref) land on the button.
      {...props}
      type="button"
      aria-pressed={memoryOff}
      aria-label={MEMORY_TOGGLE_LABEL}
      disabled={disabled}
      onClick={(event) => {
        props.onClick?.(event);
        onToggle(!memoryOff);
      }}
      data-testid="memory-toggle"
      className={cn(
        "hover:bg-surface-raised focus-visible:ring-ring inline-flex size-[38px] items-center justify-center rounded-[10px] focus-visible:ring-2 focus-visible:outline-none disabled:opacity-50 max-sm:size-11",
        memoryOff
          ? "bg-primary-subtle text-foreground"
          : "text-foreground-2 hover:text-foreground",
        className,
      )}
    >
      <BrainIcon className="size-5" aria-hidden="true" />
    </button>
  );
}
