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
      <h2 id="run-history-heading" className="text-[15px] font-semibold">
        Run history
      </h2>
      <p className="text-muted-foreground text-sm">
        The full record of each automation run (what it was asked, the tools it
        used and what they returned, and its answer), kept on this machine only.
        Secrets are redacted before anything is stored. The retention also
        applies to each automation&apos;s conversation: once its oldest content
        is past it, the automation starts a fresh conversation (forgetting
        earlier runs) and the old one is deleted.
      </p>
      {error != null && (
        <Alert variant="destructive">
          <AlertTitle>I cannot read the run history</AlertTitle>
          <AlertDescription>{error.message}</AlertDescription>
        </Alert>
      )}
      {settings?.warning && (
        <Alert data-testid="run-history-warning">
          <AlertTitle>The run history is filling up</AlertTitle>
          <AlertDescription>{settings.warning}</AlertDescription>
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
                  This deletes, from this machine, every stored automation run
                  and every automation&apos;s conversation thread. It cannot be
                  undone.
                </DialogDescription>
              </DialogHeader>
              <div className="flex flex-col gap-2 text-sm">
                <p className="font-medium">Deleted</p>
                <ul
                  className="text-muted-foreground list-disc pl-5"
                  data-testid="deletes"
                >
                  <li>
                    Every stored run: prompts, tool calls, tool results and
                    answers.
                  </li>
                  <li>
                    Each automation&apos;s conversation thread: its messages,
                    its files, and its run traces, including anything you wrote
                    in that thread yourself. The next run starts a new thread.
                  </li>
                </ul>
                <p className="font-medium">Kept</p>
                <ul
                  className="text-muted-foreground list-disc pl-5"
                  data-testid="keeps"
                >
                  <li>The automations themselves.</li>
                  <li>
                    Their delivery log: when each ran and whether it was
                    delivered, without content.
                  </li>
                  <li>
                    Messages still waiting to be delivered (held for quiet
                    hours).
                  </li>
                  <li>Your other chats.</li>
                </ul>
              </div>
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
                  Delete runs and threads
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
          {remove.data && (
            <p className="text-muted-foreground text-sm" data-testid="deleted">
              Deleted {remove.data.deleted}{" "}
              {remove.data.deleted === 1 ? "run" : "runs"} and{" "}
              {remove.data.threads_deleted ?? 0} automation{" "}
              {(remove.data.threads_deleted ?? 0) === 1 ? "thread" : "threads"}.
            </p>
          )}
          {(remove.data?.threads_failed?.length ?? 0) > 0 && (
            <Alert variant="destructive" data-testid="threads-failed">
              <AlertTitle>Some threads were not deleted</AlertTitle>
              <AlertDescription>
                {remove.data?.threads_failed?.length === 1
                  ? "1 automation thread could not be deleted and still holds its content:"
                  : `${remove.data?.threads_failed?.length} automation threads could not be deleted and still hold their content:`}{" "}
                <span className="font-mono text-xs">
                  {remove.data?.threads_failed?.join(", ")}
                </span>
              </AlertDescription>
            </Alert>
          )}
        </>
      )}
    </section>
  );
}
