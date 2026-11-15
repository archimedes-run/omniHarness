"use client";

import { CheckIcon, CopyIcon, XIcon } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { pastePreview, pasteSize } from "@/core/messages/pasted-text";
import { cn } from "@/lib/utils";

/**
 * A long paste, shown as a small card labelled with its first words. Clicking
 * it opens the whole text. In the composer it also carries a remove button.
 */
export function PastedTextCard({
  text,
  onRemove,
  className,
}: {
  text: string;
  onRemove?: () => void;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const preview = pastePreview(text);
  const size = pasteSize(text);

  return (
    <>
      <div
        data-testid="pasted-text-card"
        className={cn(
          "group/pasted border-border bg-background relative w-44 shrink-0 rounded-xl border text-left shadow-xs",
          className,
        )}
      >
        <button
          type="button"
          onClick={() => setOpen(true)}
          aria-label={`Open pasted text: ${preview}`}
          className="hover:bg-accent/50 focus-visible:ring-ring flex h-full w-full flex-col gap-2 rounded-xl p-2.5 text-left outline-none focus-visible:ring-2"
        >
          <span className="text-muted-foreground line-clamp-3 text-xs leading-4 break-words">
            {preview}
          </span>
          <span className="flex items-center gap-1.5">
            <span className="border-border text-muted-foreground rounded border px-1 py-px text-[10px] font-medium tracking-wide">
              PASTED
            </span>
            <span className="text-muted-foreground truncate text-[10px]">
              {size}
            </span>
          </span>
        </button>
        {onRemove && (
          <button
            type="button"
            onClick={onRemove}
            aria-label="Remove pasted text"
            className="bg-background border-border text-muted-foreground hover:text-foreground focus-visible:ring-ring absolute -top-1.5 -right-1.5 flex size-5 items-center justify-center rounded-full border outline-none focus-visible:ring-2"
          >
            <XIcon className="size-3" />
          </button>
        )}
      </div>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="flex max-h-[80vh] flex-col gap-3 sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>Pasted text</DialogTitle>
            <DialogDescription>{size}</DialogDescription>
          </DialogHeader>
          <pre
            data-testid="pasted-text-full"
            className="bg-muted/40 border-border min-h-0 flex-1 overflow-auto rounded-lg border p-3 font-sans text-sm leading-6 break-words whitespace-pre-wrap"
          >
            {text}
          </pre>
          <div className="flex justify-end">
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                void navigator.clipboard?.writeText(text).then(() => {
                  setCopied(true);
                  setTimeout(() => setCopied(false), 1500);
                });
              }}
            >
              {copied ? (
                <CheckIcon className="size-3.5" />
              ) : (
                <CopyIcon className="size-3.5" />
              )}
              {copied ? "Copied" : "Copy"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}

/** Folds a long message to a few lines with a "Show more" control. */
export function FoldedMessage({
  long,
  children,
}: {
  long: boolean;
  children: React.ReactNode;
}) {
  const [expanded, setExpanded] = useState(false);
  if (!long) {
    return <>{children}</>;
  }
  return (
    <div className="flex flex-col items-start gap-1">
      <div
        data-testid="folded-message"
        data-expanded={expanded}
        className={cn(
          !expanded &&
            "max-h-36 overflow-hidden [mask-image:linear-gradient(to_bottom,black_60%,transparent)]",
        )}
      >
        {children}
      </div>
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        className="text-muted-foreground hover:text-foreground focus-visible:ring-ring rounded text-xs font-medium underline-offset-2 outline-none hover:underline focus-visible:ring-2"
      >
        {expanded ? "Show less" : "Show more"}
      </button>
    </div>
  );
}
