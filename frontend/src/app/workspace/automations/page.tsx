"use client";

import Link from "next/link";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { AutomationRow } from "@/components/workspace/automations/automation-row";
import { WorkflowList } from "@/components/workspace/workflows/workflow-list";
import { useAutomationTemplates } from "@/core/automations/hooks";
import { useTriggerRules } from "@/core/triggers/hooks";
import { env } from "@/env";

/**
 * Automations = trigger rules + workflows (Phase 2.5). Rules are editable here
 * through the one validated write path; an invalid change is refused with the
 * engine's reason and the rules in force stay in force.
 *
 * Creating an automation from chat ("every weekday at 9, brief me") is a
 * Feature 005 item.
 */
export default function AutomationsPage() {
  const { view, isLoading, error } = useTriggerRules();
  const { templates } = useAutomationTemplates();

  return (
    <div className="mx-auto w-full max-w-4xl space-y-8 p-6">
      <header className="space-y-1">
        <h1 className="text-xl font-semibold">Automations</h1>
        <p className="text-muted-foreground text-sm">
          What I do without being asked: scheduled messages, alerts, and
          workflows.
        </p>
      </header>

      {isLoading && <p className="text-muted-foreground text-sm">Loading…</p>}
      {error != null && (
        <Alert variant="destructive" data-testid="unreadable">
          <AlertTitle>I cannot read the automations</AlertTitle>
          <AlertDescription>{String(error)}</AlertDescription>
        </Alert>
      )}
      {view && !view.engine_enabled && (
        <Alert data-testid="engine-disabled">
          <AlertTitle>The trigger engine is off</AlertTitle>
          <AlertDescription>
            These rules are loaded, and nothing runs them until
            trigger_engine.enabled is set.
          </AlertDescription>
        </Alert>
      )}
      {view?.rules_error && (
        <Alert variant="destructive" data-testid="rules-error">
          <AlertTitle>The rule file was not accepted</AlertTitle>
          <AlertDescription>
            The rules below are the previous ones, still in force.{" "}
            {view.rules_error}
          </AlertDescription>
        </Alert>
      )}
      {view && !view.writable && view.not_writable_reason && (
        <Alert data-testid="not-writable">
          <AlertTitle>These rules cannot be edited here</AlertTitle>
          <AlertDescription>{view.not_writable_reason}</AlertDescription>
        </Alert>
      )}

      <section className="space-y-2" aria-labelledby="rules-heading">
        <h2 id="rules-heading" className="text-sm font-semibold">
          Scheduled and alert rules
        </h2>
        {view?.rules.length === 0 && (
          <p className="text-muted-foreground text-sm" data-testid="no-rules">
            No rules yet. Start from one below.
          </p>
        )}
        <ul className="space-y-2">
          {view?.rules.map((rule) => (
            <AutomationRow
              key={rule.id}
              rule={rule}
              version={view.version}
              writable={view.writable}
            />
          ))}
        </ul>
      </section>

      {view?.writable && templates && (
        <section className="space-y-2" aria-labelledby="new-heading">
          <h2 id="new-heading" className="text-sm font-semibold">
            New automation
          </h2>
          <ul className="grid gap-2 sm:grid-cols-3">
            {templates.map((t) => (
              <li key={t.template}>
                <Link
                  href={`/workspace/automations/new?template=${t.template}`}
                  className="border-border hover:bg-muted block h-full space-y-1 rounded-md border p-3"
                  data-testid="template"
                >
                  <span className="text-foreground block font-medium">
                    {t.title}
                  </span>
                  <span className="text-muted-foreground block text-sm">
                    {t.description}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}

      {env.NEXT_PUBLIC_FEATURE_WORKFLOWS === "true" && (
        <section
          className="border-border space-y-2 border-t pt-6"
          aria-labelledby="workflows-heading"
        >
          <h2 id="workflows-heading" className="text-sm font-semibold">
            Workflows
          </h2>
          <WorkflowList />
        </section>
      )}
    </div>
  );
}
