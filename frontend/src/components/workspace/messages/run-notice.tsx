"use client";

import { AlertCircleIcon, RotateCcwIcon } from "lucide-react";
import { useId, useLayoutEffect, useRef, useState } from "react";

import type { DisclosureItem } from "@/core/disclosure";
import { cn } from "@/lib/utils";

import { useOptionalThread } from "./context";
import { DisclosureNote } from "./disclosure-note";

export const INTERRUPTED_TEXT =
  "This reply was interrupted by a restart. Ask again.";
/** The server's words when there is nothing to send again. */
export const INTERRUPTED_TEXT_NO_RETRY =
  "This reply was interrupted by a restart.";
export const ATTACHMENTS_NOT_RESENT = "Attachments are not re-sent.";

/** Likely more than two lines before it is measured (and on the server). */
const looksLong = (text: string) => text.length > 140 || text.includes("\n");

/**
 * What "Try again" will send, clipped to two lines; "Show all" opens it (a
 * real button, aria-expanded). The toggle shows only when the text is longer
 * than the clip.
 */
export function SendsAgainPreview({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const [overflows, setOverflows] = useState(() => looksLong(text));
  const ref = useRef<HTMLQuoteElement>(null);
  const id = useId();
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || open) return;
    const measure = () => setOverflows(el.scrollHeight > el.clientHeight + 1);
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [open, text]);
  return (
    <div className="min-w-0 text-sm" data-testid="run-notice-preview">
      <span className="text-muted-foreground" id={`${id}-label`}>
        Sends again:
      </span>
      <blockquote
        ref={ref}
        id={`${id}-text`}
        aria-labelledby={`${id}-label`}
        className={cn(
          "text-foreground mt-0.5 border-l-2 pl-2 break-words whitespace-pre-wrap",
          !open && "line-clamp-2",
        )}
      >
        {text}
      </blockquote>
      {(overflows || open) && (
        <button
          type="button"
          aria-expanded={open}
          aria-controls={`${id}-text`}
          onClick={() => setOpen((v) => !v)}
          data-testid="run-notice-preview-toggle"
          className="text-foreground hover:bg-surface-raised focus-visible:ring-ring mt-0.5 rounded-md px-1.5 py-0.5 text-xs underline underline-offset-2 focus-visible:ring-2 focus-visible:outline-none max-sm:py-2"
        >
          {open ? "Show less" : "Show all"}
        </button>
      )}
    </div>
  );
}

/**
 * A reply cut off by a gateway restart, shown as a notice from the system
 * (not an assistant reply): what happened, the actions that had already run
 * (DisclosureNote), and "Try again", which sends the person's message again.
 * Never sent automatically. Theme tokens only (AA in light and dark).
 */
export function RunNoticeView({
  text,
  items = [],
  retryText,
  hadAttachments = false,
  onRetry,
  disabled = false,
  className,
}: {
  text?: string;
  items?: DisclosureItem[];
  retryText: string | null;
  hadAttachments?: boolean;
  /** Absent: no button (nowhere to send it). */
  onRetry?: (text: string) => void;
  disabled?: boolean;
  className?: string;
}) {
  const resend = retryText?.trim() ? retryText : null;
  const canRetry = !!onRetry && !!resend;
  return (
    <div
      role="status"
      data-testid="run-notice"
      className={cn(
        "bg-card text-foreground my-3 flex max-w-full min-w-0 flex-col gap-2 rounded-lg border px-3 py-2 text-sm",
        className,
      )}
    >
      <p className="flex min-w-0 items-start gap-2">
        <AlertCircleIcon
          aria-hidden="true"
          className="text-muted-foreground mt-0.5 size-4 shrink-0"
        />
        <span className="min-w-0 break-words">
          {text ?? (resend ? INTERRUPTED_TEXT : INTERRUPTED_TEXT_NO_RETRY)}
        </span>
      </p>
      {canRetry && (
        <>
          <SendsAgainPreview text={resend} />
          <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
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
            {hadAttachments && (
              <span
                className="text-muted-foreground min-w-0 text-xs break-words"
                data-testid="run-notice-attachments"
              >
                {ATTACHMENTS_NOT_RESENT}
              </span>
            )}
          </div>
        </>
      )}
      <DisclosureNote items={items} className="-mt-1 -ml-1.5" />
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
  hadAttachments,
  className,
}: {
  text?: string;
  items?: DisclosureItem[];
  retryText: string | null;
  hadAttachments?: boolean;
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
      hadAttachments={hadAttachments}
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
