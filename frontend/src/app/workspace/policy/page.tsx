"use client";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { TierCheckForm } from "@/components/workspace/policy/tier-check";
import { WithheldNotice } from "@/components/workspace/withheld-notice";
import { usePolicyRules, useTier3Audit } from "@/core/policy/hooks";

export default function PolicyPage() {
  const { rules, error } = usePolicyRules();
  const { executions } = useTier3Audit();

  return (
    <div className="mx-auto w-full max-w-5xl space-y-6 p-6">
      <header className="space-y-1">
        <h1 className="text-xl font-semibold">Permission policy</h1>
        <p className="text-muted-foreground text-sm">
          What each tool is allowed to do without asking, and what I have done
          with your confirmation.
        </p>
      </header>

      {error != null && (
        <Alert variant="destructive" data-testid="unreadable">
          <AlertTitle>I cannot read the policy</AlertTitle>
          <AlertDescription>{String(error)}</AlertDescription>
        </Alert>
      )}
      {/* FR-029: the rules shown are the ones enforced, and a refused edit says so. */}
      {rules?.kept_previous && (
        <Alert variant="destructive" data-testid="kept-previous">
          <AlertTitle>Your last edit to the rules was refused</AlertTitle>
          <AlertDescription>
            The rules below are the previous ones, still in force. {rules.error}
          </AlertDescription>
        </Alert>
      )}
      {rules?.unreadable && !rules.kept_previous && (
        <Alert variant="destructive" data-testid="all-tier-3">
          <AlertTitle>No readable rules: every tool is Tier 3</AlertTitle>
          <AlertDescription>{rules.error}</AlertDescription>
        </Alert>
      )}

      <TierCheckForm />

      <section className="space-y-2" aria-labelledby="rules-heading">
        <h2 id="rules-heading" className="text-sm font-semibold">
          Rules in force
        </h2>
        {rules && (
          <p className="text-muted-foreground text-xs">
            {rules.source_file} · a bare confirmation covers up to{" "}
            {rules.threshold_targets} items · plans expire after{" "}
            {Math.round(rules.expires_after_seconds / 3600)} h
          </p>
        )}
        <ul className="space-y-1" data-testid="rules">
          {rules?.rules.map((rule) => (
            <li
              key={`${rule.pattern}-${rule.source_line}`}
              className="border-border flex items-center justify-between rounded-md border px-3 py-2"
              data-testid="rule"
            >
              <code className="text-foreground text-sm">{rule.pattern}</code>
              <span className="flex items-center gap-2">
                {rule.exceptions.length > 0 && (
                  <span className="text-muted-foreground text-xs">
                    {rule.exceptions.length} exception(s)
                  </span>
                )}
                <Badge variant={rule.tier === 3 ? "destructive" : "secondary"}>
                  Tier {rule.tier}
                </Badge>
              </span>
            </li>
          ))}
        </ul>
      </section>

      <section className="space-y-2" aria-labelledby="audit-heading">
        <h2 id="audit-heading" className="text-sm font-semibold">
          Recent Tier 3 actions
        </h2>
        {executions?.length === 0 && (
          <p
            className="text-muted-foreground text-sm"
            data-testid="no-executions"
          >
            Nothing has been done with your confirmation yet.
          </p>
        )}
        <ul className="space-y-2">
          {executions?.map((run) => (
            <li
              key={`${run.at}-${run.tool}`}
              className="border-border space-y-1 rounded-md border p-3"
              data-testid="execution"
            >
              {run.withheld ? (
                <WithheldNotice text={run.plan_as_stated} />
              ) : (
                <p className="text-foreground text-sm" data-testid="plan">
                  {run.plan_as_stated}
                </p>
              )}
              <p className="text-muted-foreground text-xs">
                {new Date(run.at).toLocaleString()} · {run.tool} · acted as{" "}
                {run.actor} · authorised by{" "}
                <span data-testid="authorised-by">
                  {run.authorised_by ?? "not recorded"}
                </span>
              </p>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
