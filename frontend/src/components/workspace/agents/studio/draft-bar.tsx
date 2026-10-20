"use client";

import { SparkleIcon } from "lucide-react";
import { useState } from "react";

import { cn } from "@/lib/utils";

import { outlineButton } from "./studio-frame";

/**
 * "Describe it in one sentence" and Draft (Agent-Studio.dc.html,
 * Skill-Studio.dc.html). Draft is an outline button: Save is the screen's one
 * solid button (design-notes #1). What it drafts is shown for review; the
 * caller saves nothing until Save.
 */
export function DraftBar({
  label,
  placeholder,
  draftLabel,
  draftingLabel,
  needsSentence,
  emphasis,
  onDraft,
  testId,
}: {
  label: string;
  placeholder: string;
  draftLabel: string;
  draftingLabel: string;
  needsSentence: string;
  /** The agent board draws this bar with the accent border. */
  emphasis?: boolean;
  onDraft: (sentence: string) => Promise<void>;
  testId: string;
}) {
  const [sentence, setSentence] = useState("");
  const [busy, setBusy] = useState(false);
  const [hint, setHint] = useState<string | null>(null);

  async function run() {
    if (!sentence.trim()) {
      setHint(needsSentence);
      return;
    }
    setHint(null);
    setBusy(true);
    try {
      await onDraft(sentence.trim());
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <div
        className={cn(
          "bg-card flex flex-wrap items-center gap-2 rounded-xl border px-3 py-2",
          emphasis ? "border-primary" : "border-border-strong",
        )}
        data-testid={testId}
      >
        <SparkleIcon className="text-primary size-4" aria-hidden />
        <label className="block min-w-0 flex-[1_1_320px]">
          <span className="sr-only">{label}</span>
          <input
            type="text"
            value={sentence}
            placeholder={placeholder}
            onChange={(e) => setSentence(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                void run();
              }
            }}
            className="text-foreground placeholder:text-muted-foreground min-h-11 w-full bg-transparent text-sm outline-none md:min-h-0"
          />
        </label>
        <button
          type="button"
          className={cn(outlineButton, "px-3 py-1.5")}
          onClick={() => void run()}
          disabled={busy}
          aria-busy={busy}
        >
          {busy ? draftingLabel : draftLabel}
        </button>
      </div>
      {hint ? (
        <p className="text-muted-foreground mt-1.5 text-xs" role="status">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

/** The note under a draft: who drafted it and that nothing is saved. */
export function DraftNote({
  note,
}: {
  note: { text: string; bad: boolean } | null;
}) {
  if (!note) return null;
  return (
    <p
      className={cn(
        "text-xs",
        note.bad ? "text-destructive" : "text-muted-foreground",
      )}
      role={note.bad ? "alert" : "status"}
      data-testid="draft-note"
    >
      {note.text}
    </p>
  );
}
