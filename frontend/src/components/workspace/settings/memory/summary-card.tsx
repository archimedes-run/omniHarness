"use client";

import { PencilIcon } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useUpdateMemorySection } from "@/core/memory/hooks";
import { formatTimeAgo } from "@/core/utils/datetime";
import { cn } from "@/lib/utils";

/** Past this, a section says it may be out of date. */
const STALE_DAYS = 30;
/** Longer than this collapses behind "Show more". */
const LONG = 320;

export function isStale(updatedAt: string, now = Date.now()): boolean {
  const at = Date.parse(updatedAt);
  return Number.isFinite(at) && now - at > STALE_DAYS * 24 * 60 * 60 * 1000;
}

/**
 * One memory summary as a calm card (Phase 2.6): a title, the text at normal
 * size as plain paragraphs (no markdown, no code-styled dates, no quotes), a
 * small muted "Updated 2 months ago", "may be out of date" past 30 days, and
 * an inline editor so a wrong summary can be corrected.
 */
export function SummaryCard({
  title,
  group,
  sectionKey,
  summary,
  updatedAt,
}: {
  title: string;
  group: string;
  sectionKey: string;
  summary: string;
  updatedAt: string;
}) {
  const save = useUpdateMemorySection();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(summary);
  const [expanded, setExpanded] = useState(false);
  const long = summary.length > LONG;
  const paragraphs = summary.split(/\n{2,}/).filter((p) => p.trim());

  return (
    <section
      className="border-border bg-card group space-y-2 rounded-xl border p-4"
      data-testid="summary-card"
      data-section={`${group}.${sectionKey}`}
    >
      <div className="flex items-start justify-between gap-2">
        <h3 className="text-foreground text-sm font-semibold">{title}</h3>
        {!editing && (
          <Button
            variant="ghost"
            size="icon-sm"
            className="text-muted-foreground -mt-1 -mr-1 opacity-0 group-focus-within:opacity-100 group-hover:opacity-100 focus-visible:opacity-100"
            aria-label={`Edit ${title}`}
            onClick={() => {
              setDraft(summary);
              setEditing(true);
            }}
          >
            <PencilIcon />
          </Button>
        )}
      </div>

      {editing ? (
        <form
          className="space-y-2"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate(
              { group, key: sectionKey, summary: draft },
              { onSuccess: () => setEditing(false) },
            );
          }}
        >
          <Textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            rows={Math.min(10, Math.max(3, Math.ceil(draft.length / 90)))}
            aria-label={`${title} summary`}
            autoFocus
          />
          {save.error != null && (
            <p className="text-destructive text-sm" role="alert">
              {save.error.message}
            </p>
          )}
          <div className="flex gap-2">
            <Button type="submit" size="sm" disabled={save.isPending}>
              Save
            </Button>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => setEditing(false)}
            >
              Cancel
            </Button>
          </div>
        </form>
      ) : summary.trim() ? (
        <>
          <div
            className={cn(
              "text-foreground space-y-2 text-sm leading-relaxed",
              long && !expanded && "line-clamp-4",
            )}
            data-testid="summary-text"
          >
            {paragraphs.map((p, i) => (
              <p key={i}>{p}</p>
            ))}
          </div>
          {long && (
            <button
              type="button"
              className="text-muted-foreground hover:text-foreground text-xs font-medium"
              onClick={() => setExpanded(!expanded)}
            >
              {expanded ? "Show less" : "Show more"}
            </button>
          )}
        </>
      ) : (
        <p className="text-muted-foreground text-sm">Nothing here yet.</p>
      )}

      {updatedAt && !editing && (
        <p className="text-muted-foreground text-xs" data-testid="updated">
          Updated {formatTimeAgo(updatedAt)}
          {isStale(updatedAt) && (
            <span data-testid="stale"> · may be out of date</span>
          )}
        </p>
      )}
    </section>
  );
}
