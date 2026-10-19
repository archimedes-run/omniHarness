"use client";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { FiringRow } from "@/components/workspace/triggers/firing-row";
import { RuleRow } from "@/components/workspace/triggers/rule-row";
import { useTriggerFirings, useTriggerRules } from "@/core/triggers/hooks";

export default function TriggersPage() {
  const rules = useTriggerRules();
  const firings = useTriggerFirings();

  return (
    <div className="mx-auto w-full max-w-5xl space-y-4 p-6">
      <header className="space-y-1">
        <h1 className="text-xl font-semibold">Triggers</h1>
        <p className="text-muted-foreground text-sm">
          The rules that make me speak first, and what each has done.
        </p>
      </header>

      {rules.view && !rules.view.engine_enabled && (
        <Alert data-testid="engine-disabled">
          <AlertTitle>The trigger engine is off</AlertTitle>
          <AlertDescription>
            These rules are loaded, and nothing evaluates them until
            trigger_engine.enabled is set.
          </AlertDescription>
        </Alert>
      )}
      {rules.view?.rules_error && (
        <Alert variant="destructive" data-testid="rules-error">
          <AlertTitle>The rule file was not accepted</AlertTitle>
          <AlertDescription>{rules.view.rules_error}</AlertDescription>
        </Alert>
      )}
      {(rules.error != null || firings.error != null) && (
        <Alert variant="destructive" data-testid="unreadable">
          <AlertTitle>I cannot read the trigger records</AlertTitle>
          <AlertDescription>
            {String(rules.error ?? firings.error)}
          </AlertDescription>
        </Alert>
      )}

      <div className="grid gap-6 md:grid-cols-2">
        <section className="space-y-2" aria-labelledby="rules-heading">
          <h2 id="rules-heading" className="text-sm font-semibold">
            Rules
          </h2>
          <ul className="space-y-2">
            {rules.view?.rules.map((rule) => (
              <RuleRow key={rule.id} rule={rule} />
            ))}
          </ul>
        </section>
        <section className="space-y-2" aria-labelledby="firings-heading">
          <h2 id="firings-heading" className="text-sm font-semibold">
            Firings
          </h2>
          {firings.view?.firings.length === 0 && (
            <p
              className="text-muted-foreground text-sm"
              data-testid="no-firings"
            >
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
      </div>
    </div>
  );
}
