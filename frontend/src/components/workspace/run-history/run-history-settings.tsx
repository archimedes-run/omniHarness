"use client";

import { useState } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  useDeleteRunHistory,
  useRunHistorySettings,
  useSaveRetention,
} from "@/core/run-history/hooks";

/**
 * Settings: the run history (Feature 006). What each automation run did, in
 * full, kept on this machine only, secrets redacted before storing; how long
 * it is kept; and deleting all of it, behind a confirmation.
 */
export function RunHistorySettings() {
  const { settings, error } = useRunHistorySettings();
  const save = useSaveRetention();
  const remove = useDeleteRunHistory();
  const [days, setDays] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const value = days ?? String(settings?.retention_days ?? "");

  return (
    <section
      className="flex flex-col gap-3"
      aria-labelledby="run-history-heading"
      data-testid="run-history-settings"
    >
      <h2 id="run-history-heading" className="text-sm font-semibold">
        Run history
      </h2>
      <p className="text-muted-foreground text-sm">
        The full record of each automation run (what it was asked, the tools it
        used and what they returned, and its answer), kept on this machine only.
        Secrets are redacted before anything is stored.
      </p>
      {error != null && (
        <Alert variant="destructive">
          <AlertTitle>I cannot read the run history</AlertTitle>
          <AlertDescription>{error.message}</AlertDescription>
        </Alert>
      )}
      {settings && (
        <>
          <p className="text-sm" data-testid="run-count">
            {settings.runs === 1 ? "1 run" : `${settings.runs} runs`} stored in{" "}
            <span className="font-mono text-xs">{settings.location}</span>
          </p>
          <form
            className="flex flex-wrap items-center gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              save.mutate(Number(value), { onSuccess: () => setDays(null) });
            }}
          >
            <label className="flex items-center gap-2 text-sm">
              Keep runs for
              <Input
                type="number"
                min={1}
                max={3650}
                value={value}
                onChange={(e) => setDays(e.target.value)}
                className="w-24"
                aria-label="Days to keep runs"
              />
              days
            </label>
            <Button
              type="submit"
              variant="outline"
              disabled={days === null || save.isPending}
            >
              Save
            </Button>
          </form>
          {save.error != null && (
            <p className="text-destructive text-sm" role="alert">
              {save.error.message}
            </p>
          )}
          <Dialog open={confirming} onOpenChange={setConfirming}>
            <DialogTrigger asChild>
              <Button
                variant="outline"
                className="self-start"
                disabled={settings.runs === 0}
              >
                Delete run history
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Delete the run history?</DialogTitle>
                <DialogDescription>
                  Every stored automation run is deleted from this machine. The
                  automations themselves, and their delivery log, are kept. This
                  cannot be undone.
                </DialogDescription>
              </DialogHeader>
              {remove.error != null && (
                <p className="text-destructive text-sm" role="alert">
                  {remove.error.message}
                </p>
              )}
              <DialogFooter>
                <DialogClose asChild>
                  <Button variant="ghost">Keep it</Button>
                </DialogClose>
                <Button
                  variant="destructive"
                  disabled={remove.isPending}
                  onClick={() =>
                    remove.mutate(undefined, {
                      onSuccess: () => setConfirming(false),
                    })
                  }
                >
                  Delete all runs
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
          {remove.data && (
            <p className="text-muted-foreground text-sm" data-testid="deleted">
              Deleted {remove.data.deleted}{" "}
              {remove.data.deleted === 1 ? "run" : "runs"}.
            </p>
          )}
        </>
      )}
    </section>
  );
}
