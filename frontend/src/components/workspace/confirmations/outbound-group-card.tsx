"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  canDecline,
  formatExpiresIn,
  isExpired,
  originLabel,
  outboundSubject,
} from "@/core/confirmations/logic";
import type { PendingAction, ResolveResult } from "@/core/confirmations/types";

import { LongText } from "./plan-text";

const KIND: Record<string, string> = {
  web_search: "Search",
  web_fetch: "Open page",
  image_search: "Image search",
};

const DONE: Record<string, string> = {
  executed: "Done",
  declined: "Declined",
  already_resolved: "Already handled",
  expired: "Expired",
  failed: "Did not complete",
  chat_deleted: "Chat deleted",
};

/** Outcomes after which a call has nothing left to press. */
const SETTLED = new Set(Object.keys(DONE));

/**
 * A turn's outbound calls, waiting together (Feature 007): the lead read the
 * person's private data earlier in this turn, so each lookup that leaves the
 * machine (web_search, web_fetch, image_search) asks first. ONE card lists
 * every call, with "Apply all" (the confirmations apply-all route: each call
 * runs once, and the lead then carries on with the results) and a Decline per
 * call. Only these buttons confirm: content suggested the calls, so a typed
 * "yes" does not count. Every text field arrives made safe by loadPending.
 */
export function OutboundGroupCard({
  actions,
  results,
  busy,
  applying,
  applyError,
  onDecline,
  onApplyAll,
}: {
  actions: PendingAction[];
  results: Record<string, ResolveResult | undefined>;
  busy: boolean;
  applying: boolean;
  applyError?: string | null;
  onDecline: (id: string) => void;
  onApplyAll: (ids: string[]) => void;
}) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  const open = actions.filter(
    (a) => !isExpired(a, now) && !SETTLED.has(results[a.id]?.outcome ?? "none"),
  );
  const earliest = [...actions].sort((a, b) =>
    a.expires_at.localeCompare(b.expires_at),
  )[0]!;
  const suggestedBy = originLabel(actions[0]!);

  return (
    <section
      aria-label="Approval needed"
      className="border-warning bg-card flex flex-col gap-3 rounded-xl border px-4 py-3.5"
      data-testid="outbound-group"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-warning text-[13px] font-semibold">
          Needs your approval · {actions.length} outside lookups
        </span>
        <span className="text-muted-foreground text-xs" data-testid="remaining">
          {formatExpiresIn(earliest.expires_at, now)}
        </span>
      </div>
      <p className="text-muted-foreground text-sm">
        This conversation read your private data, so lookups that leave your
        computer wait for you. Nothing below has been sent.
      </p>
      {suggestedBy && (
        <p
          className="border-border text-muted-foreground rounded-md border px-3 py-2 text-sm"
          data-testid="origin-label"
        >
          <span className="text-foreground font-medium">{suggestedBy}</span>,
          not by you. Only the buttons here can approve them.
        </p>
      )}
      <ul
        className="border-border divide-border divide-y rounded-md border"
        data-testid="outbound-calls"
      >
        {actions.map((action) => {
          const result = results[action.id];
          const outcome = result?.outcome;
          const settled = SETTLED.has(outcome ?? "none");
          return (
            <li
              key={action.id}
              className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-sm"
              data-testid="outbound-call"
              data-action-id={action.id}
              data-outcome={outcome ?? "open"}
            >
              <div className="min-w-0 flex-1 break-words">
                <span className="text-muted-foreground mr-2 text-xs uppercase">
                  {KIND[action.tool_name] ?? action.tool_name}
                </span>
                <span className="text-foreground">
                  <LongText text={outboundSubject(action)} cutAt={90} />
                </span>
                {result && !settled && (
                  <span className="text-muted-foreground mt-1 block text-xs">
                    {result.message}
                  </span>
                )}
              </div>
              {settled ? (
                <span
                  className="text-muted-foreground text-xs"
                  data-testid="outbound-call-status"
                >
                  {DONE[outcome!]}
                </span>
              ) : (
                <Button
                  size="sm"
                  variant="outline"
                  data-testid="outbound-decline"
                  disabled={busy || applying || !canDecline(action, now)}
                  onClick={() => onDecline(action.id)}
                >
                  Decline
                </Button>
              )}
            </li>
          );
        })}
      </ul>
      {applyError && (
        <p role="alert" className="text-destructive text-sm">
          Not done: {applyError}
        </p>
      )}
      {open.length > 0 && (
        <div className="flex flex-wrap items-center justify-end gap-2">
          <Button
            data-testid="outbound-apply-all"
            disabled={busy || applying}
            onClick={() => onApplyAll(open.map((a) => a.id))}
          >
            {applying ? "Running…" : `Apply all ${open.length}`}
          </Button>
        </div>
      )}
    </section>
  );
}
