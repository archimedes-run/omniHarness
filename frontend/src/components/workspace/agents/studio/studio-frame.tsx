"use client";

import * as TabsPrimitive from "@radix-ui/react-tabs";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * The layout Agent Studio and Skill Studio share (Agent-Studio.dc.html,
 * Skill-Studio.dc.html): a rail of items on the left with "+ New" on top, and
 * the selected item on the right: a header, a real tablist (arrow keys from
 * Radix), the tab's content, and a footer with the actions. At narrow widths
 * the rail stacks above the detail and every target is 44 px tall.
 */
export function StudioFrame({
  rail,
  railLabel,
  children,
  testId,
}: {
  rail: ReactNode;
  railLabel: string;
  children: ReactNode;
  testId: string;
}) {
  return (
    <div
      className="flex min-h-full flex-col md:h-full md:flex-row"
      data-testid={testId}
    >
      <nav
        aria-label={railLabel}
        className="border-border flex shrink-0 flex-col gap-1 border-b px-2.5 py-3.5 md:w-[250px] md:overflow-y-auto md:border-r md:border-b-0"
        data-testid="studio-rail"
      >
        {rail}
      </nav>
      <div className="flex min-w-0 flex-1 flex-col md:min-h-0">{children}</div>
    </div>
  );
}

export function RailNew({
  label,
  onClick,
  selected,
}: {
  label: string;
  onClick: () => void;
  selected: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={selected}
      data-testid="studio-new"
      className={cn(
        "border-border-strong text-foreground hover:bg-accent focus-visible:ring-ring mb-2 min-h-11 rounded-lg border border-dashed px-3 py-2 text-left text-sm outline-none focus-visible:ring-2 md:min-h-0",
        selected && "bg-surface-raised font-medium",
      )}
    >
      {label}
    </button>
  );
}

export function RailItem({
  selected,
  onClick,
  avatar,
  children,
  testId,
}: {
  selected: boolean;
  onClick: () => void;
  avatar?: ReactNode;
  children: ReactNode;
  testId?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-current={selected ? "page" : undefined}
      data-testid={testId}
      className={cn(
        "focus-visible:ring-ring flex min-h-11 items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-sm outline-none focus-visible:ring-2 md:min-h-0",
        avatar ? "" : "px-3",
        selected
          ? "bg-surface-raised text-foreground font-medium"
          : "text-foreground-2 hover:bg-accent",
      )}
    >
      {avatar}
      <span className="min-w-0 truncate">{children}</span>
    </button>
  );
}

export function StudioTabs<T extends string>({
  label,
  tabs,
  value,
  onChange,
  header,
  children,
  footer,
}: {
  label: string;
  tabs: { id: T; label: string }[];
  value: T;
  onChange: (id: T) => void;
  header: ReactNode;
  children: ReactNode;
  footer: ReactNode;
}) {
  return (
    <TabsPrimitive.Root
      value={value}
      onValueChange={(v) => onChange(v as T)}
      className="flex min-h-0 flex-1 flex-col"
    >
      <div className="px-4 pt-5 sm:px-7">{header}</div>
      <TabsPrimitive.List
        aria-label={label}
        className="border-border flex flex-wrap gap-1 border-b px-4 pt-4 sm:px-7"
      >
        {tabs.map((tab) => (
          <TabsPrimitive.Trigger
            key={tab.id}
            value={tab.id}
            data-testid={`studio-tab-${tab.id}`}
            className="text-muted-foreground hover:text-foreground focus-visible:ring-ring data-[state=active]:border-primary data-[state=active]:text-foreground min-h-11 border-b-2 border-transparent px-3 py-2 text-sm outline-none focus-visible:ring-2 data-[state=active]:font-medium md:min-h-0"
          >
            {tab.label}
          </TabsPrimitive.Trigger>
        ))}
      </TabsPrimitive.List>
      <div className="min-h-0 flex-1 md:overflow-y-auto">
        <div className="box-border w-full max-w-[760px] px-4 py-6 sm:px-7">
          {children}
        </div>
      </div>
      <div className="border-border flex flex-wrap items-center justify-end gap-2.5 border-t px-4 py-3.5 sm:px-7">
        {footer}
      </div>
    </TabsPrimitive.Root>
  );
}

export const TabPanel = TabsPrimitive.Content;

/** Outline button, the board's secondary action (one solid per screen). */
export const outlineButton =
  "border-border-strong text-foreground hover:bg-accent focus-visible:ring-ring inline-flex min-h-11 items-center justify-center gap-1.5 rounded-lg border px-4 py-2 text-sm outline-none focus-visible:ring-2 disabled:opacity-50 md:min-h-0";

/** The one solid primary button on the screen. */
export const solidButton =
  "bg-primary text-primary-foreground hover:bg-primary/90 focus-visible:ring-ring inline-flex min-h-11 items-center justify-center rounded-lg px-4 py-2 text-sm font-semibold outline-none focus-visible:ring-2 focus-visible:ring-offset-2 disabled:opacity-50 md:min-h-0";

/** A card on the surface fill, as the Overview stats. */
export const statCard = "bg-card border-border rounded-xl border px-4 py-3.5";

export const fieldClass =
  "bg-card border-border-strong text-foreground placeholder:text-muted-foreground focus-visible:ring-ring rounded-lg border px-3 py-2.5 text-sm outline-none focus-visible:ring-2";

/** A chip: tool group, skill. */
export const chipClass =
  "bg-card border-border-strong text-foreground inline-flex min-h-11 items-center gap-2 rounded-lg border px-2.5 py-1.5 text-sm md:min-h-0";

export const dashedChip =
  "border-border-strong text-foreground-2 hover:bg-accent focus-visible:ring-ring inline-flex min-h-11 items-center rounded-lg border border-dashed px-3 py-1.5 text-sm outline-none focus-visible:ring-2 md:min-h-0";
