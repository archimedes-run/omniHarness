"use client";

import { useEffect, useState } from "react";

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
import { Textarea } from "@/components/ui/textarea";
import {
  useApplyMemoryCleanup,
  useClearMemory,
  useCreateMemoryFact,
  useMemoryCleanupPreview,
} from "@/core/memory/hooks";

const CATEGORIES = [
  "preference",
  "context",
  "knowledge",
  "behavior",
  "goal",
  "correction",
];

const SECTION_TITLE: Record<string, string> = {
  "user.workContext": "Work",
  "user.personalContext": "Personal",
  "user.topOfMind": "Top of mind",
  "history.recentMonths": "Recent months",
  "history.earlierContext": "Earlier",
  "history.longTermBackground": "Background",
};

export function AddFactDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const create = useCreateMemoryFact();
  const [content, setContent] = useState("");
  const [category, setCategory] = useState("preference");
  useEffect(() => {
    if (open) {
      setContent("");
      setCategory("preference");
      create.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add a fact</DialogTitle>
          <DialogDescription>
            Something durable I should remember about you.
          </DialogDescription>
        </DialogHeader>
        <form
          id="add-fact"
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate(
              { content: content.trim(), category, confidence: 1 },
              { onSuccess: () => onOpenChange(false) },
            );
          }}
        >
          <Textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder="e.g. Prefers answers with a table first"
            aria-label="Fact"
            rows={3}
            autoFocus
          />
          <label className="flex items-center gap-2 text-sm">
            Category
            <select
              className="border-input bg-background text-foreground rounded-md border px-2 py-1.5 text-sm"
              value={category}
              onChange={(e) => setCategory(e.target.value)}
            >
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>
          {create.error != null && (
            <p className="text-destructive text-sm" role="alert">
              {create.error.message}
            </p>
          )}
        </form>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            type="submit"
            form="add-fact"
            disabled={!content.trim() || create.isPending}
          >
            Add fact
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** Clearing everything is irreversible, so it takes typing CLEAR. */
export function ClearMemoryDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const clear = useClearMemory();
  const [typed, setTyped] = useState("");
  useEffect(() => {
    if (open) setTyped("");
  }, [open]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Clear all memory?</DialogTitle>
          <DialogDescription>
            Every summary and fact is deleted, and this cannot be undone. Export
            first if you might want it back. Type CLEAR to confirm.
          </DialogDescription>
        </DialogHeader>
        <Input
          value={typed}
          onChange={(e) => setTyped(e.target.value)}
          placeholder="CLEAR"
          aria-label="Type CLEAR to confirm"
          autoFocus
        />
        {clear.error != null && (
          <p className="text-destructive text-sm" role="alert">
            {clear.error.message}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Keep my memory
          </Button>
          <Button
            variant="destructive"
            disabled={typed !== "CLEAR" || clear.isPending}
            onClick={() =>
              clear.mutate(undefined, { onSuccess: () => onOpenChange(false) })
            }
          >
            Clear all memory
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** Sentence-level: what the cleanup removes from a section, struck through. */
function SectionDiff({ before, after }: { before: string; after: string }) {
  const kept = new Set(
    after
      .split(/(?<=[.!?])\s+/)
      .map((s) => s.trim())
      .filter(Boolean),
  );
  const sentences = before
    .split(/(?<=[.!?])\s+/)
    .map((s) => s.trim())
    .filter(Boolean);
  const rewritten = sentences.some((s) => !kept.has(s)) && after.trim();
  return (
    <div className="space-y-2 text-sm">
      <p className="leading-relaxed">
        {sentences.map((s, i) =>
          kept.has(s) ? (
            <span key={i}>{s} </span>
          ) : (
            <del
              key={i}
              className="bg-destructive/10 text-muted-foreground decoration-destructive/60"
            >
              {s}{" "}
            </del>
          ),
        )}
      </p>
      {rewritten && (
        <p className="border-success/40 bg-success/10 rounded-md border-l-2 px-3 py-2 leading-relaxed">
          {after}
        </p>
      )}
    </div>
  );
}

/**
 * The one-time "clean up memory" (Phase 2.6): the memory model rewrites each
 * summary under the durability rules, the page shows before and after, and
 * nothing is saved until accepted. Each change can be left out.
 */
export function CleanupMemoryDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const preview = useMemoryCleanupPreview();
  const apply = useApplyMemoryCleanup();
  const [skipped, setSkipped] = useState<Set<string>>(new Set());
  useEffect(() => {
    if (open) {
      setSkipped(new Set());
      apply.reset();
      preview.mutate();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const data = preview.data;
  const changed = data?.sections.filter((s) => s.changed) ?? [];
  const facts = data?.factsToRemove ?? [];
  const toggle = (id: string) =>
    setSkipped((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const accepted = changed.filter((s) => !skipped.has(`${s.group}.${s.key}`));
  const acceptedFacts = facts.filter((f) => f.id && !skipped.has(f.id));

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Clean up memory</DialogTitle>
          <DialogDescription>
            Keeps preferences, projects, people and context; drops file paths,
            commands and step-by-step task details. Review each change; nothing
            is saved until you apply it.
          </DialogDescription>
        </DialogHeader>

        {preview.isPending && (
          <p
            className="text-muted-foreground text-sm"
            data-testid="cleanup-working"
          >
            Reading your memory and rewriting it under the new rules…
          </p>
        )}
        {preview.error != null && (
          <p className="text-destructive text-sm" role="alert">
            {preview.error.message}
          </p>
        )}
        {data && changed.length === 0 && facts.length === 0 && (
          <p
            className="text-muted-foreground text-sm"
            data-testid="cleanup-clean"
          >
            Nothing to clean up: your memory already keeps to durable things.
          </p>
        )}

        {changed.map((s) => {
          const id = `${s.group}.${s.key}`;
          return (
            <section
              key={id}
              className="border-border space-y-2 rounded-lg border p-3"
              data-testid="cleanup-section"
            >
              <label className="flex items-center gap-2 text-sm font-semibold">
                <input
                  type="checkbox"
                  checked={!skipped.has(id)}
                  onChange={() => toggle(id)}
                />
                {SECTION_TITLE[id] ?? id}
              </label>
              <SectionDiff before={s.before} after={s.after} />
            </section>
          );
        })}

        {facts.length > 0 && (
          <section className="border-border space-y-2 rounded-lg border p-3">
            <h3 className="text-sm font-semibold">Facts to forget</h3>
            <ul className="space-y-1">
              {facts.map((f) => (
                <li key={f.id ?? f.content}>
                  <label className="flex items-start gap-2 text-sm">
                    <input
                      type="checkbox"
                      className="mt-1"
                      checked={f.id != null && !skipped.has(f.id)}
                      disabled={f.id == null}
                      onChange={() => f.id && toggle(f.id)}
                    />
                    <span>{f.content}</span>
                  </label>
                </li>
              ))}
            </ul>
          </section>
        )}

        {apply.error != null && (
          <p className="text-destructive text-sm" role="alert">
            {apply.error.message}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            disabled={
              !data ||
              apply.isPending ||
              (accepted.length === 0 && acceptedFacts.length === 0)
            }
            onClick={() =>
              data &&
              apply.mutate(
                {
                  version: data.version,
                  sections: Object.fromEntries(
                    accepted.map((s) => [`${s.group}.${s.key}`, s.after]),
                  ),
                  factsToRemove: acceptedFacts.map((f) => f.id!),
                },
                { onSuccess: () => onOpenChange(false) },
              )
            }
          >
            Apply {accepted.length + acceptedFacts.length} change
            {accepted.length + acceptedFacts.length === 1 ? "" : "s"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
