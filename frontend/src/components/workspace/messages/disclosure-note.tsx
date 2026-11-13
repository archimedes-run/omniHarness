"use client";

import { ChevronDownIcon, InfoIcon } from "lucide-react";
import { useId, useState } from "react";

import { type DisclosureItem, disclosureSummary } from "@/core/disclosure";
import { cn } from "@/lib/utils";

/**
 * Actions that ran without a confirmation (Tier 2), as a note from the system
 * under the answer (spec 009 Slice 0). Collapsed to one line; the records open
 * as a disclosure (keyboard: Tab to the button, Enter or Space).
 */
export function DisclosureNote({
  items,
  className,
}: {
  items: DisclosureItem[];
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  if (!items.length) return null;
  const plain = items.filter((i) => !i.grant);
  const granted = items.filter((i) => i.grant);
  return (
    <div
      className={cn("mt-1 text-xs", className)}
      data-testid="disclosure-note"
    >
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((v) => !v)}
        className="text-muted-foreground hover:text-foreground focus-visible:ring-ring inline-flex items-center gap-1.5 rounded-md px-1.5 py-1 focus-visible:ring-2 focus-visible:outline-none"
      >
        <InfoIcon className="size-3.5" aria-hidden="true" />
        <span className="flex flex-col items-start gap-0.5 text-left">
          {plain.length > 0 && (
            <span data-testid="disclosure-plain">
              Ran without asking:{" "}
              <span className="font-mono">{disclosureSummary(plain)}</span>
            </span>
          )}
          {granted.length > 0 && (
            <span data-testid="disclosure-grant">
              Ran under grant:{" "}
              <span className="font-mono">{disclosureSummary(granted)}</span>
            </span>
          )}
        </span>
        <ChevronDownIcon
          aria-hidden="true"
          className={cn("size-3.5 transition-transform", open && "rotate-180")}
        />
      </button>
      {open && (
        <ul
          id={panelId}
          aria-label="Actions that ran without a confirmation"
          className="bg-card text-foreground-2 mt-1 max-w-[640px] list-disc rounded-lg border py-2 pr-3 pl-7"
          data-testid="disclosure-details"
        >
          {items.map((item, i) => (
            <li key={i} className="break-words">
              {item.text || item.tool}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
