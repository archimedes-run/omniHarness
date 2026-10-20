"use client";

import * as React from "react";

import { TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";

/**
 * The Graphite page parts (Feature 006 boards: Connections, MCP Suite,
 * Settings): one column, a 24 px title with a muted line under it, underline
 * tabs, 14 px-radius cards and divided rows. Pages without a board of their
 * own use these too, so every app page reads as the same product.
 */

export function PageColumn({
  width = "wide",
  className,
  children,
  ...props
}: React.ComponentProps<"div"> & { width?: "wide" | "narrow" }) {
  return (
    <div
      className={cn(
        // 14 px body, as the boards: explicit sizes override it.
        "mx-auto flex w-full flex-col gap-[22px] px-4 pt-8 pb-10 text-sm md:px-8",
        width === "wide" ? "max-w-[1040px]" : "max-w-[760px] gap-5",
        className,
      )}
      {...props}
    >
      {children}
    </div>
  );
}

export function PageHeader({
  title,
  description,
  actions,
  titleId,
}: {
  title: React.ReactNode;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  titleId?: string;
}) {
  return (
    <div className="flex flex-wrap items-end gap-4">
      <div className="min-w-0 flex-[1_1_320px]">
        <h1 id={titleId} className="text-2xl font-semibold">
          {title}
        </h1>
        {description && (
          <p className="text-muted-foreground mt-1">{description}</p>
        )}
      </div>
      {actions && (
        <div className="flex flex-wrap items-center gap-2">{actions}</div>
      )}
    </div>
  );
}

/** Underline tabs (a real tablist: Radix gives arrow keys and roles). */
export function UnderlineTabsList({
  className,
  ...props
}: React.ComponentProps<typeof TabsList>) {
  return (
    <TabsList
      variant="line"
      className={cn(
        "border-border h-auto w-full justify-start gap-1 rounded-none border-b p-0",
        className,
      )}
      {...props}
    />
  );
}

export function UnderlineTab({
  className,
  ...props
}: React.ComponentProps<typeof TabsTrigger>) {
  return (
    <TabsTrigger
      className={cn(
        // The underline is the line variant's ::after, in the accent, on the
        // list's bottom border.
        "text-muted-foreground data-[state=active]:text-foreground hover:text-foreground after:bg-primary h-auto flex-none rounded-none border-0 px-3 py-2 text-sm font-normal group-data-[orientation=horizontal]/tabs:after:bottom-[-1px] data-[state=active]:font-medium max-md:min-h-11",
        className,
      )}
      {...props}
    />
  );
}

/** A surface card: 14 px radius, the border token, the card fill. */
export function PageCard({
  className,
  as: Comp = "div",
  ...props
}: React.HTMLAttributes<HTMLElement> & {
  as?: "div" | "section" | "article" | "li";
}) {
  return (
    <Comp
      className={cn(
        "bg-card border-border rounded-xl border px-[18px] py-4",
        className,
      )}
      {...props}
    />
  );
}

/** A card of divided rows (the boards' server and session lists). */
export function RowList({ className, ...props }: React.ComponentProps<"ul">) {
  return (
    <ul
      className={cn(
        "bg-card border-border divide-border divide-y overflow-hidden rounded-xl border",
        className,
      )}
      {...props}
    />
  );
}

export function SectionHeading({
  className,
  ...props
}: React.ComponentProps<"h2">) {
  return (
    <h2 className={cn("text-[15px] font-semibold", className)} {...props} />
  );
}

export type StatusTone = "good" | "warn" | "bad" | "muted";

export const TONE_TEXT: Record<StatusTone, string> = {
  good: "text-success",
  warn: "text-warning",
  bad: "text-destructive",
  muted: "text-muted-foreground",
};

/** A status in words, coloured by tone (never colour alone). */
export function StatusWord({
  tone,
  className,
  ...props
}: React.ComponentProps<"span"> & { tone: StatusTone }) {
  return (
    <span className={cn("text-xs", TONE_TEXT[tone], className)} {...props} />
  );
}
