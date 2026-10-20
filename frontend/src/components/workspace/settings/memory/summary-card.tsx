"use client";

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
      className="border-border bg-card flex flex-col gap-2 rounded-xl border px-[18px] py-4"
      data-testid="summary-card"
      data-section={`${group}.${sectionKey}`}
    >
      <div className="flex items-center gap-2.5">
        <h3 className="text-foreground flex-1 text-[15px] font-semibold">
          {title}
        </h3>
        {!editing && (
          <button
            type="button"
            className="text-primary text-sm hover:underline max-md:min-h-11"
            aria-label={`Edit ${title}`}
            onClick={() => {
              setDraft(summary);
              setEditing(true);
            }}
          >
            Edit
          </button>
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
              "text-foreground-2 space-y-2 text-sm leading-relaxed",
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
              className="text-muted-foreground hover:text-foreground self-start text-sm"
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
            <span>
              {" · "}
              <span className="text-warning" data-testid="stale">
                may be out of date
              </span>
            </span>
          )}
        </p>
      )}
    </section>
  );
}
