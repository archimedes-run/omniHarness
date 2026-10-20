"use client";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { TierCheckForm } from "@/components/workspace/policy/tier-check";
import { usePolicyRules } from "@/core/policy/hooks";

export default function SafetyPage() {
  const { rules, error } = usePolicyRules();

  return (
    <div className="mx-auto w-full max-w-5xl space-y-6 p-6">
      <header className="space-y-1">
        <h1 className="text-xl font-semibold">Safety</h1>
        <p className="text-muted-foreground text-sm">
          What each tool is allowed to do without asking. What has been done
          with your confirmation is in the Activity log.
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

      {/* FR-023: absent, not forbidden. No rule could allow these. */}
      {rules?.cannot_do && rules.cannot_do.length > 0 && (
        <section className="space-y-2" aria-labelledby="cannot-heading">
          <h2 id="cannot-heading" className="text-sm font-semibold">
            What I can&apos;t do
          </h2>
          <p className="text-muted-foreground text-xs">
            No tool exists for these, so no rule can allow them.
          </p>
          <ul className="space-y-1" data-testid="cannot-do">
            {rules.cannot_do.map((item) => (
              <li
                key={item.capability}
                className="border-border rounded-md border px-3 py-2 text-sm"
              >
                <span className="text-foreground font-medium capitalize">
                  {item.capability}
                </span>
                <p className="text-muted-foreground mt-0.5">{item.wording}</p>
              </li>
            ))}
          </ul>
        </section>
      )}

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
    </div>
  );
}
