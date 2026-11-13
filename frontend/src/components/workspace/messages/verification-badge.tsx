"use client";

import {
  CheckCircle2Icon,
  ChevronDownIcon,
  CircleAlertIcon,
  ListTreeIcon,
} from "lucide-react";
import Link from "next/link";
import { useId, useState } from "react";

import {
  badgeFor,
  traceHref,
  type VerificationRecord,
} from "@/core/verification";
import { cn } from "@/lib/utils";

const TONE = {
  success: "border-success/40 bg-success/10 text-success",
  warning: "border-warning/40 bg-warning/10 text-warning",
} as const;

/**
 * Verified / Unverified, under a finished answer (spec 009 Slice 0). The
 * state is the server's record (evidence the agent's loop recorded), never the
 * reply's own words. The details open as a disclosure (keyboard: Tab to the
 * button, Enter or Space).
 */
export function VerificationBar({
  record,
  className,
}: {
  record: VerificationRecord | null;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  if (!record) return null;
  const badge = badgeFor(record);
  if (!badge && !record.run_id) return null;
  const Icon = badge?.tone === "success" ? CheckCircle2Icon : CircleAlertIcon;
  return (
    <div
      className={cn("mt-2 flex flex-col gap-2", className)}
      data-testid="verification-bar"
    >
      <div className="flex flex-wrap items-center gap-2 text-xs">
        {badge && (
          <button
            type="button"
            aria-expanded={open}
            aria-controls={panelId}
            onClick={() => setOpen((v) => !v)}
            data-testid="verification-badge"
            data-status={record.status}
            className={cn(
              "focus-visible:ring-ring inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-medium focus-visible:ring-2 focus-visible:outline-none",
              TONE[badge.tone],
            )}
          >
            <Icon className="size-3.5" aria-hidden="true" />
            {badge.label}
            <span className="sr-only">: {badge.summary}. Show details</span>
            <ChevronDownIcon
              aria-hidden="true"
              className={cn(
                "size-3.5 transition-transform",
                open && "rotate-180",
              )}
            />
          </button>
        )}
        {record.run_id && (
          <Link
            href={traceHref(record.run_id)}
            className="text-muted-foreground hover:text-foreground focus-visible:ring-ring inline-flex items-center gap-1 rounded-md px-1.5 py-1 underline-offset-2 hover:underline focus-visible:ring-2 focus-visible:outline-none"
            data-testid="open-trace"
          >
            <ListTreeIcon className="size-3.5" aria-hidden="true" />
            Open trace
          </Link>
        )}
      </div>
      {badge && open && (
        <div
          id={panelId}
          role="region"
          aria-label="Verification details"
          className="bg-card text-foreground-2 max-w-[640px] rounded-lg border p-3 text-sm"
          data-testid="verification-details"
        >
          <VerificationDetails record={record} />
        </div>
      )}
    </div>
  );
}

export function VerificationDetails({
  record,
}: {
  record: VerificationRecord;
}) {
  return (
    <div className="flex flex-col gap-3">
      {record.done_criteria && (
        <p>
          <span className="text-foreground font-medium">Done when: </span>
          {record.done_criteria}
        </p>
      )}
      {record.checks.length > 0 && (
        <ul className="flex flex-col gap-1.5" aria-label="Checks">
          {record.checks.map((check, i) => (
            <li key={i} className="flex items-start gap-2">
              {check.verified ? (
                <CheckCircle2Icon
                  className="text-success mt-0.5 size-4 shrink-0"
                  aria-hidden="true"
                />
              ) : (
                <CircleAlertIcon
                  className="text-warning mt-0.5 size-4 shrink-0"
                  aria-hidden="true"
                />
              )}
              <span>
                <span className="sr-only">
                  {check.verified ? "Verified: " : "Not verified: "}
                </span>
                <span className="text-foreground">{check.claim}</span>
                {check.evidence && (
                  <span className="text-muted-foreground">
                    {" "}
                    — {check.evidence}
                  </span>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
      {record.not_verified.length > 0 && (
        <div>
          <p className="text-foreground font-medium">Not verified</p>
          <ul className="mt-1 list-disc pl-5">
            {record.not_verified.map((item, i) => (
              <li key={i}>{item}</li>
            ))}
          </ul>
        </div>
      )}
      {(record.links.verified.length > 0 ||
        record.links.unverified.length > 0) && (
        <p className="text-muted-foreground">
          Links: {record.links.verified.length} found in this run&apos;s tool
          results, {record.links.unverified.length} not found
        </p>
      )}
    </div>
  );
}
