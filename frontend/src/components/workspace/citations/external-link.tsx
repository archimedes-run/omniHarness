"use client";

import { ExternalLinkIcon } from "lucide-react";
import { useState, type ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { defangHost } from "@/core/display/defang";
import { cn } from "@/lib/utils";

/**
 * A link to another origin found in agent, model or tool text
 * (core/streamdown/content-url-guard.ts took its href away). It is a button:
 * nothing is fetched until the person reads the full URL and chooses to open
 * it, and then it opens with no opener and no referrer. Content-derived URLs
 * are never live links; only the app's own links are.
 */
export function ExternalLink({
  href,
  children,
  className,
}: {
  href: string;
  children: ReactNode;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const label = typeof children === "string" ? children : null;
  const citation = label ? /^citation:\s*(.*)$/i.exec(label) : null;
  const host = defangHost(href);

  return (
    <>
      {citation ? (
        <button
          type="button"
          className="inline-flex cursor-pointer items-center align-baseline"
          data-external-link=""
          onClick={(e) => {
            e.stopPropagation();
            setOpen(true);
          }}
        >
          <Badge
            variant="secondary"
            className="hover:bg-secondary/80 mx-0.5 gap-1 rounded-full px-2 py-0.5 text-xs font-normal"
          >
            {citation[1] && citation[1] !== "Source" ? citation[1] : host}
            <ExternalLinkIcon className="size-3" />
          </Badge>
        </button>
      ) : (
        <button
          type="button"
          data-external-link=""
          title={`Outside link to ${host}`}
          className={cn(
            "text-primary decoration-primary/30 hover:decoration-primary/60 inline cursor-pointer text-left underline underline-offset-2 transition-colors",
            className,
          )}
          onClick={(e) => {
            e.stopPropagation();
            setOpen(true);
          }}
        >
          {children}
        </button>
      )}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Open an outside link?</DialogTitle>
            <DialogDescription>
              This link came from the conversation, not from OmniHarness. It
              goes to {host || "another site"}, and anything in it is sent
              there.
            </DialogDescription>
          </DialogHeader>
          <p className="bg-muted text-foreground rounded-md p-3 font-mono text-xs break-all">
            {href}
          </p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={() => {
                window.open(href, "_blank", "noopener,noreferrer");
                setOpen(false);
              }}
            >
              Open link
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
