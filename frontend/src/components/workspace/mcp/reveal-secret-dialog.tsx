"use client";

import { Loader2Icon } from "lucide-react";
import { useId, useState, type RefObject } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";

/**
 * Asks for the account password before a stored secret is shown.
 *
 * Radix Dialog gives the focus trap and Esc to close; with no DialogTrigger
 * it cannot know the opener, so `returnFocusTo` is focused on close. The
 * title and description label the dialog.
 * `onReveal` resolves to an error message to show, or null when it worked.
 */
export function RevealSecretDialog({
  open,
  keyName,
  onOpenChange,
  onReveal,
  returnFocusTo,
}: {
  open: boolean;
  keyName: string;
  returnFocusTo: RefObject<HTMLElement | null>;
  onOpenChange: (open: boolean) => void;
  onReveal: (password: string) => Promise<string | null>;
}) {
  const inputId = useId();
  const errorId = useId();
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const close = (next: boolean) => {
    if (!next) {
      setPassword("");
      setError(null);
    }
    onOpenChange(next);
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!password || busy) return;
    setBusy(true);
    setError(null);
    try {
      const problem = await onReveal(password);
      if (problem === null) {
        close(false);
      } else {
        setError(problem);
        setPassword("");
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent
        className="bg-card border-border sm:max-w-md"
        onCloseAutoFocus={(e) => {
          e.preventDefault();
          returnFocusTo.current?.focus();
        }}
      >
        <form onSubmit={(e) => void submit(e)} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>
              Reveal <span className="font-mono">{keyName}</span>
            </DialogTitle>
            <DialogDescription>
              Enter your account password to show the stored value. Each reveal
              is recorded.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-2">
            <label
              htmlFor={inputId}
              className="text-foreground text-sm font-medium"
            >
              Your password
            </label>
            <Input
              id={inputId}
              type="password"
              autoComplete="current-password"
              autoFocus
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              aria-invalid={error !== null}
              aria-describedby={error ? errorId : undefined}
            />
            {error && (
              <p id={errorId} role="alert" className="text-destructive text-sm">
                {error}
              </p>
            )}
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => close(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={!password || busy}>
              {busy && <Loader2Icon className="size-4 animate-spin" />}
              Reveal
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
