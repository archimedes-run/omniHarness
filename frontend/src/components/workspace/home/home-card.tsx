import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * One Home card (Main board): a 14 px surface with a small muted heading.
 * Every card says when it cannot tell; `CantTell` is that sentence.
 */
export function HomeCard({
  id,
  title,
  action,
  children,
  className,
  testId,
}: {
  id: string;
  title: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  testId?: string;
}) {
  return (
    <section
      aria-labelledby={id}
      data-testid={testId}
      className={cn(
        "bg-card text-card-foreground border-border flex flex-col gap-3 rounded-xl border px-5 py-[18px]",
        className,
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <h2
          id={id}
          className="text-muted-foreground m-0 text-[13px] font-semibold"
        >
          {title}
        </h2>
        {action}
      </div>
      {children}
    </section>
  );
}

/** "Can't tell": a source could not be read. Never drawn like "none". */
export function CantTell({
  children,
  testId,
}: {
  children: ReactNode;
  testId?: string;
}) {
  return (
    <p
      className="text-warning text-sm"
      data-testid={testId}
      data-state="cant-tell"
    >
      {children}
    </p>
  );
}

/** A known-empty source, said plainly. */
export function Empty({
  children,
  testId,
}: {
  children: ReactNode;
  testId?: string;
}) {
  return (
    <p
      className="text-muted-foreground text-sm"
      data-testid={testId}
      data-state="empty"
    >
      {children}
    </p>
  );
}

export function Loading() {
  return <p className="text-muted-foreground text-sm">Loading…</p>;
}
