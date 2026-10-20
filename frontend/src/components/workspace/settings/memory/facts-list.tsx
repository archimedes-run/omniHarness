"use client";

import { CheckIcon, PencilIcon, SearchIcon, XIcon } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  useCreateMemoryFact,
  useDeleteMemoryFact,
  useUpdateMemoryFact,
} from "@/core/memory/hooks";
import type { MemoryFact } from "@/core/memory/types";
import { formatTimeAgo } from "@/core/utils/datetime";

/**
 * Facts (Phase 2.6): searchable; each row its text, a category chip and when
 * it was learned, with edit and forget on hover (and on keyboard focus).
 * Forget is one click; Undo puts the fact back.
 */
export function FactsList({ facts }: { facts: MemoryFact[] }) {
  const [query, setQuery] = useState("");
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    const sorted = [...facts].sort((a, b) =>
      b.createdAt.localeCompare(a.createdAt),
    );
    return q
      ? sorted.filter(
          (f) =>
            f.content.toLowerCase().includes(q) ||
            f.category.toLowerCase().includes(q),
        )
      : sorted;
  }, [facts, query]);

  if (facts.length === 0) {
    return (
      <div
        className="text-muted-foreground rounded-xl border border-dashed p-8 text-center text-sm"
        data-testid="facts-empty"
      >
        No facts yet. As you talk, I&apos;ll note durable things here —
        preferences, people, what you&apos;re working on. You can add one
        yourself too.
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="relative">
        <SearchIcon className="text-muted-foreground pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2" />
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={`Search ${facts.length} facts`}
          aria-label="Search facts"
          className="pl-9"
        />
      </div>
      {shown.length === 0 ? (
        <p className="text-muted-foreground text-sm" data-testid="facts-none">
          No fact matches “{query}”.
        </p>
      ) : (
        <ul className="divide-border divide-y" data-testid="facts">
          {shown.map((fact) => (
            <FactRow key={fact.id} fact={fact} />
          ))}
        </ul>
      )}
    </div>
  );
}

function FactRow({ fact }: { fact: MemoryFact }) {
  const update = useUpdateMemoryFact();
  const remove = useDeleteMemoryFact();
  const create = useCreateMemoryFact();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(fact.content);

  const forget = () =>
    remove.mutate(fact.id, {
      onSuccess: () =>
        toast("Forgotten", {
          description:
            fact.content.length > 60
              ? `${fact.content.slice(0, 60)}…`
              : fact.content,
          action: {
            label: "Undo",
            // Puts it back as it was; the backend gives it a new id.
            onClick: () =>
              create.mutate({
                content: fact.content,
                category: fact.category,
                confidence: fact.confidence,
              }),
          },
          duration: 8000,
        }),
      onError: (error) => toast.error(error.message),
    });

  return (
    <li className="group flex items-start gap-3 py-3" data-testid="fact">
      <div className="min-w-0 flex-1 space-y-1">
        {editing ? (
          <form
            className="flex items-center gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              update.mutate(
                { factId: fact.id, input: { content: draft.trim() } },
                { onSuccess: () => setEditing(false) },
              );
            }}
          >
            <Input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              aria-label="Fact"
              autoFocus
            />
            <Button
              type="submit"
              size="icon-sm"
              variant="ghost"
              aria-label="Save fact"
              disabled={!draft.trim() || update.isPending}
            >
              <CheckIcon />
            </Button>
            <Button
              type="button"
              size="icon-sm"
              variant="ghost"
              aria-label="Cancel"
              onClick={() => {
                setDraft(fact.content);
                setEditing(false);
              }}
            >
              <XIcon />
            </Button>
          </form>
        ) : (
          <p className="text-foreground text-sm">{fact.content}</p>
        )}
        <div className="flex items-center gap-2">
          <Badge variant="secondary" className="font-normal">
            {fact.category}
          </Badge>
          {fact.createdAt && (
            <span className="text-muted-foreground text-xs">
              learned {formatTimeAgo(fact.createdAt)}
            </span>
          )}
        </div>
      </div>
      {!editing && (
        <div className="flex shrink-0 gap-1 opacity-0 group-focus-within:opacity-100 group-hover:opacity-100">
          <Button
            size="icon-sm"
            variant="ghost"
            aria-label="Edit fact"
            onClick={() => setEditing(true)}
          >
            <PencilIcon />
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="text-muted-foreground"
            disabled={remove.isPending}
            onClick={forget}
          >
            Forget this
          </Button>
        </div>
      )}
    </li>
  );
}
