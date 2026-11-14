"use client";

import { AlertCircleIcon, RotateCcwIcon } from "lucide-react";
import { useRef, useState } from "react";

import type { DisclosureItem } from "@/core/disclosure";
import { cn } from "@/lib/utils";

import { useOptionalThread } from "./context";
import { DisclosureNote } from "./disclosure-note";

export const INTERRUPTED_TEXT =
  "This reply was interrupted by a restart. Ask again.";

/**
 * A reply cut off by a gateway restart, shown as a notice from the system
 * (not an assistant reply): what happened, the actions that had already run
 * (DisclosureNote), and "Try again", which sends the person's message again.
 * Never sent automatically. Theme tokens only (AA in light and dark).
 */
export function RunNoticeView({
  text = INTERRUPTED_TEXT,
  items = [],
  retryText,
  onRetry,
  disabled = false,
  className,
}: {
  text?: string;
  items?: DisclosureItem[];
  retryText: string | null;
  /** Absent: no button (nowhere to send it). */
  onRetry?: (text: string) => void;
  disabled?: boolean;
  className?: string;
}) {
  const resend = retryText?.trim() ? retryText : null;
  return (
    <div
      role="status"
      data-testid="run-notice"
      className={cn(
        "bg-card text-foreground my-3 flex max-w-full min-w-0 flex-col gap-1 rounded-lg border px-3 py-2 text-sm",
        className,
      )}
    >
      <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-2">
        <p className="flex min-w-0 flex-1 basis-56 items-start gap-2">
          <AlertCircleIcon
            aria-hidden="true"
            className="text-muted-foreground mt-0.5 size-4 shrink-0"
          />
          <span className="min-w-0 break-words">{text}</span>
        </p>
        {onRetry && resend && (
          <button
            type="button"
            disabled={disabled}
            onClick={() => onRetry(resend)}
            data-testid="run-notice-retry"
            className="bg-surface-raised border-border text-foreground hover:border-border-strong focus-visible:ring-ring inline-flex h-8 shrink-0 items-center gap-1.5 rounded-md border px-3 text-sm focus-visible:ring-2 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50 max-sm:h-11"
          >
            <RotateCcwIcon aria-hidden="true" className="size-3.5" />
            Try again
          </button>
        )}
      </div>
      <DisclosureNote items={items} className="-ml-1.5" />
    </div>
  );
}

/**
 * "Try again" sends at most once: a second click (even before the re-render
 * disables the button) and a click while a run is under way do nothing.
 */
export function guardRetry(
  retry: (text: string) => void,
  isBlocked: () => boolean,
  markSent: () => void,
) {
  return (text: string) => {
    if (isBlocked()) return;
    markSent();
    retry(text);
  };
}

/** The notice wired to the chat: sends at most once, waits for a run. */
export function RunNotice({
  text,
  items,
  retryText,
  className,
}: {
  text?: string;
  items?: DisclosureItem[];
  retryText: string | null;
  className?: string;
}) {
  const ctx = useOptionalThread();
  const retry = ctx?.retry;
  const busy = !!ctx?.thread.isLoading;
  const [sent, setSent] = useState(false);
  const sentRef = useRef(false);
  return (
    <RunNoticeView
      text={text}
      items={items}
      retryText={retryText}
      className={className}
      disabled={sent || busy}
      onRetry={
        retry
          ? guardRetry(
              retry,
              () => sentRef.current || busy,
              () => {
                sentRef.current = true;
                setSent(true);
              },
            )
          : undefined
      }
    />
  );
}
