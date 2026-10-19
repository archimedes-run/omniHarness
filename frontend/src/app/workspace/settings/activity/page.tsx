"use client";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Tier3AuditList } from "@/components/workspace/policy/tier3-audit";
import { FiringRow } from "@/components/workspace/triggers/firing-row";
import { useTriggerFirings } from "@/core/triggers/hooks";

/**
 * Settings → Activity log (Phase 2.5): what the assistant did on its own
 * initiative (trigger firings, reasons verbatim, batches named) and what it did
 * with your confirmation (the Tier 3 audit).
 */
export default function ActivityLogPage() {
  const firings = useTriggerFirings();
  return (
    <div className="mx-auto w-full max-w-4xl space-y-8 p-6">
      <header className="space-y-1">
        <h1 className="text-xl font-semibold">Activity log</h1>
        <p className="text-muted-foreground text-sm">
          What I did on my own initiative, and what I did with your
          confirmation.
        </p>
      </header>

      <section className="space-y-2" aria-labelledby="firings-heading">
        <h2 id="firings-heading" className="text-sm font-semibold">
          Automation firings
        </h2>
        {firings.error != null && (
          <Alert variant="destructive" data-testid="unreadable">
            <AlertTitle>I cannot read the trigger records</AlertTitle>
            <AlertDescription>{String(firings.error)}</AlertDescription>
          </Alert>
        )}
        {firings.view?.firings.length === 0 && (
          <p className="text-muted-foreground text-sm" data-testid="no-firings">
            Nothing has fired yet.
          </p>
        )}
        <ul className="space-y-2">
          {firings.view?.firings.map((firing) => (
            <FiringRow
              key={`${firing.at}-${firing.rule_id}-${firing.event_id}-${firing.outcome}`}
              firing={firing}
            />
          ))}
        </ul>
      </section>

      <Tier3AuditList />
    </div>
  );
}
