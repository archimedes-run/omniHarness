"use client";

import { cn } from "@/lib/utils";

export interface SuggestItem {
  key: string;
  label: string;
  hint?: string;
  leading?: React.ReactNode;
  /** Listed but not choosable; the hint says why. */
  disabled?: boolean;
}

/**
 * The "@" and "/" dropdowns. Focus stays in the message box (a combobox): the
 * box owns the arrow keys, Enter and Esc, and points at the active option with
 * aria-activedescendant, so typing never stops.
 */
export function SuggestMenu({
  id,
  title,
  items,
  active,
  empty,
  onPick,
  onHover,
}: {
  id: string;
  title: string;
  items: SuggestItem[];
  active: number;
  empty: string;
  onPick: (index: number) => void;
  onHover: (index: number) => void;
}) {
  return (
    <div
      className="bg-popover text-popover-foreground border-border-strong absolute bottom-full left-0 z-50 mb-2 w-full max-w-[420px] rounded-xl border p-1.5 shadow-xl"
      data-testid="suggest-menu"
    >
      <div
        className="text-muted-foreground px-2.5 py-1.5 text-xs"
        id={`${id}-title`}
      >
        {title}
      </div>
      <ul role="listbox" id={id} aria-labelledby={`${id}-title`}>
        {items.map((item, index) => (
          <li
            key={item.key}
            id={`${id}-opt-${index}`}
            role="option"
            aria-selected={index === active}
            aria-disabled={item.disabled ? true : undefined}
            className={cn(
              "flex min-h-11 items-center gap-2.5 rounded-md px-2.5 py-2 text-sm",
              item.disabled ? "cursor-not-allowed" : "cursor-pointer",
              index === active && "bg-surface-raised",
            )}
            onMouseDown={(e) => {
              // Keep focus in the message box.
              e.preventDefault();
              if (!item.disabled) onPick(index);
            }}
            onMouseEnter={() => onHover(index)}
          >
            {item.leading}
            <span className="min-w-0 flex-1">
              <span className="block truncate">{item.label}</span>
              {item.hint && (
                <span className="text-muted-foreground block truncate text-xs">
                  {item.hint}
                </span>
              )}
            </span>
            {index === active && !item.disabled && (
              <span className="text-muted-foreground text-xs" aria-hidden>
                Enter
              </span>
            )}
          </li>
        ))}
        {items.length === 0 && (
          <li
            className="text-muted-foreground px-2.5 py-2 text-sm"
            role="presentation"
          >
            {empty}
          </li>
        )}
      </ul>
    </div>
  );
}
