"use client";

import { Badge } from "@/components/ui/badge";
import {
  PageCard,
  PageColumn,
  PageHeader,
  RowList,
  SectionHeading,
} from "@/components/workspace/page-kit";
import { TierCheckForm } from "@/components/workspace/policy/tier-check";
import { SafetyToolSources } from "@/components/workspace/settings/safety-tool-sources";
import { usePolicyRules } from "@/core/policy/hooks";

/**
 * Settings > Safety (Feature 006): the tool sources (from /workspace/tool-
 * sources) and the policy (from /workspace/policy), both of which redirect
 * here. What has been done with your confirmation is in the Activity log.
 */
export default function SafetyPage() {
  const { rules, error } = usePolicyRules();

  return (
    <PageColumn width="narrow">
      <PageHeader
        title="Safety"
        description="Where your agents' tools come from, and what each is allowed to do without asking. What was done with your confirmation is in the Activity log."
      />

      {error != null && (
        <Problem testId="unreadable" title="I cannot read the policy">
          {String(error)}
        </Problem>
      )}
      {/* FR-029: the rules shown are the ones enforced, and a refused edit says so. */}
      {rules?.kept_previous && (
        <Problem
          testId="kept-previous"
          title="Your last edit to the rules was refused"
        >
          The rules below are the previous ones, still in force. {rules.error}
        </Problem>
      )}
      {rules?.unreadable && !rules.kept_previous && (
        <Problem
          testId="all-tier-3"
          title="No readable rules: every tool is Tier 3"
        >
          {rules.error}
        </Problem>
      )}

      <SafetyToolSources />

      <TierCheckForm />

      {/* FR-023: absent, not forbidden. No rule could allow these. */}
      {rules?.cannot_do && rules.cannot_do.length > 0 && (
        <section
          className="flex flex-col gap-3"
          aria-labelledby="cannot-heading"
        >
          <SectionHeading id="cannot-heading">
            What I can&apos;t do
          </SectionHeading>
          <p className="text-muted-foreground text-sm">
            No tool exists for these, so no rule can allow them.
          </p>
          <RowList data-testid="cannot-do">
            {rules.cannot_do.map((item) => (
              <li key={item.capability} className="px-[18px] py-3 text-sm">
                <span className="text-foreground font-medium capitalize">
                  {item.capability}
                </span>
                <p className="text-muted-foreground mt-0.5">{item.wording}</p>
              </li>
            ))}
          </RowList>
        </section>
      )}

      <section className="flex flex-col gap-3" aria-labelledby="rules-heading">
        <SectionHeading id="rules-heading">Rules in force</SectionHeading>
        {rules && (
          <p className="text-muted-foreground text-sm">
            <span className="font-mono text-xs">{rules.source_file}</span> · a
            bare confirmation covers up to {rules.threshold_targets} items ·
            plans expire after {Math.round(rules.expires_after_seconds / 3600)}{" "}
            h
          </p>
        )}
        <RowList data-testid="rules">
          {rules?.rules.map((rule) => (
            <li
              key={`${rule.pattern}-${rule.source_line}`}
              className="flex items-center justify-between gap-3 px-[18px] py-3"
              data-testid="rule"
            >
              <code className="text-foreground font-mono text-[13px]">
                {rule.pattern}
              </code>
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
        </RowList>
      </section>
    </PageColumn>
  );
}

function Problem({
  testId,
  title,
  children,
}: {
  testId: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <PageCard className="border-destructive" data-testid={testId} role="alert">
      <div className="font-medium">{title}</div>
      <p className="text-muted-foreground text-[13px]">{children}</p>
    </PageCard>
  );
}
