"use client";

import { Loader2Icon, PlugIcon } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import type { CatalogEntry, SourceView } from "@/core/apps/api";
import {
  connectComposioToolkit,
  type ConnectOutcome,
} from "@/core/mcp/connect";

const OUTCOME: Record<ConnectOutcome, string> = {
  connected: "Connected. The tile will update in a moment.",
  "already-connected": "Already connected. The tile will update in a moment.",
  "timed-out": "No answer from the sign-in window. Try again if it closed.",
  blocked:
    "The browser blocked the sign-in window. Allow pop-ups and try again.",
  cancelled: "Cancelled.",
  failed: "Sign-in did not finish. Try again.",
};

/** "GOOGLECALENDAR" → "Googlecalendar"; the catalog has no display name. */
function toolkitLabel(toolkit: string): string {
  const known: Record<string, string> = {
    googlecalendar: "Google Calendar",
    gmail: "Gmail",
    github: "GitHub",
  };
  const slug = toolkit.toLowerCase();
  return known[slug] ?? slug.charAt(0).toUpperCase() + slug.slice(1);
}

/**
 * Spec 011 FR-024: the host page's own Connect sheet. An app asks for it with
 * `connect` (a tile in `not_connected`); the frame never starts OAuth. The
 * sheet names the source in the gateway's words and runs the existing
 * connector flow from this page's own button.
 */
export function ConnectSheet({
  source,
  entry,
  onClose,
  onConnected,
}: {
  source: SourceView | null;
  entry: CatalogEntry | undefined;
  onClose: () => void;
  onConnected: (source: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const toolkit = entry?.toolkit ?? null;

  const run = async () => {
    if (!source || !toolkit) return;
    setBusy(true);
    setMessage(null);
    try {
      const outcome = await connectComposioToolkit(toolkit.toLowerCase());
      setMessage(OUTCOME[outcome]);
      if (outcome === "connected" || outcome === "already-connected") {
        onConnected(source.name);
      }
    } catch (err) {
      setMessage(
        err instanceof Error ? err.message : "Could not start sign-in.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <Sheet
      open={source !== null}
      onOpenChange={(open) => {
        if (!open) {
          setMessage(null);
          onClose();
        }
      }}
    >
      <SheetContent side="right" data-testid="app-connect-sheet">
        <SheetHeader>
          <SheetTitle>
            {toolkit ? `Connect ${toolkitLabel(toolkit)}` : "Connect"}
          </SheetTitle>
          <SheetDescription>
            This app asked to show data it cannot read yet.
          </SheetDescription>
        </SheetHeader>
        {source && (
          <div className="flex flex-col gap-4 px-4 text-sm">
            <p className="border-border rounded-md border px-3 py-2">
              {source.words}
            </p>
            {toolkit ? (
              <>
                <p className="text-muted-foreground">
                  Sign-in runs here, in OmniHarness, not in the app. The app
                  only ever sees the data listed above.
                </p>
                <Button
                  type="button"
                  onClick={() => void run()}
                  disabled={busy}
                  data-testid="app-connect-button"
                  className="max-md:min-h-11"
                >
                  {busy ? (
                    <Loader2Icon className="animate-spin" />
                  ) : (
                    <PlugIcon />
                  )}
                  Connect {toolkitLabel(toolkit)}
                </Button>
              </>
            ) : (
              <p className="text-muted-foreground">
                This source is part of OmniHarness and needs no account.
              </p>
            )}
            {message && (
              <p role="status" className="text-muted-foreground">
                {message}
              </p>
            )}
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
