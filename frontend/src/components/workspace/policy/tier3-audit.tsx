"use client";

import { WithheldNotice } from "@/components/workspace/withheld-notice";
import { useTier3Audit } from "@/core/policy/hooks";

/** Tier 3 actions taken with the user's confirmation, newest first: the plan
 * as stated (or Withheld, FR-031), who acted and who authorised. */
export function Tier3AuditList() {
  const { executions } = useTier3Audit();
  return (
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
  );
}
