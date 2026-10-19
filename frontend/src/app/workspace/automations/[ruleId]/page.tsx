"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { RuleForm } from "@/components/workspace/automations/rule-form";
import { FiringRow } from "@/components/workspace/triggers/firing-row";
import { useDeleteRule } from "@/core/automations/hooks";
import { useTriggerFirings, useTriggerRules } from "@/core/triggers/hooks";

/** One automation: edit it, delete it, and see everything it has done. */
export default function AutomationPage() {
  const { ruleId } = useParams<{ ruleId: string }>();
  const id = decodeURIComponent(ruleId);
  const router = useRouter();
  const { view, isLoading } = useTriggerRules();
  const firings = useTriggerFirings();
  const remove = useDeleteRule();
  const [confirmDelete, setConfirmDelete] = useState(false);
  const rule = view?.rules.find((r) => r.id === id);
  const history = firings.view?.firings.filter((f) => f.rule_id === id);

  return (
    <div className="mx-auto w-full max-w-3xl space-y-8 p-6">
      <header className="space-y-1">
        <Link
          href="/workspace/automations"
          className="text-muted-foreground text-sm hover:underline"
        >
          ← Automations
        </Link>
        <h1 className="text-xl font-semibold">{id}</h1>
      </header>

      {isLoading && <p className="text-muted-foreground text-sm">Loading…</p>}
      {view && !rule && (
        <Alert data-testid="no-such-rule">
          <AlertTitle>There is no automation called {id}</AlertTitle>
          <AlertDescription>
            It may have been deleted or renamed.
          </AlertDescription>
        </Alert>
      )}
      {view && rule && !view.writable && view.not_writable_reason && (
        <Alert data-testid="not-writable">
          <AlertTitle>This rule cannot be edited here</AlertTitle>
          <AlertDescription>{view.not_writable_reason}</AlertDescription>
        </Alert>
      )}

      {view && rule && (
        <RuleForm
          key={`${rule.id}-${view.version}`}
          mode="edit"
          version={view.version}
          writable={view.writable}
          initial={{
            id: rule.id,
            type: rule.type,
            enabled: rule.enabled,
            match: rule.match,
            prompt: rule.prompt,
            destination: rule.destination,
            urgent: rule.urgent,
          }}
        />
      )}

      {view?.writable && rule && (
        <section className="border-border space-y-2 border-t pt-6">
          {remove.error != null && (
            <p className="text-destructive text-sm" data-testid="delete-error">
              {remove.error.message}
            </p>
          )}
          {confirmDelete ? (
            <div className="flex items-center gap-2">
              <Button
                variant="destructive"
                disabled={remove.isPending}
                onClick={() =>
                  view.version &&
                  remove.mutate(
                    { id, version: view.version },
                    { onSuccess: () => router.push("/workspace/automations") },
                  )
                }
              >
                Delete {id}
              </Button>
              <Button variant="ghost" onClick={() => setConfirmDelete(false)}>
                Keep it
              </Button>
            </div>
          ) : (
            <Button variant="outline" onClick={() => setConfirmDelete(true)}>
              Delete this automation
            </Button>
          )}
        </section>
      )}

      <section className="space-y-2" aria-labelledby="history-heading">
        <h2 id="history-heading" className="text-sm font-semibold">
          What it has done
        </h2>
        {firings.error != null && (
          <Alert variant="destructive" data-testid="history-unreadable">
            <AlertTitle>I cannot read its history</AlertTitle>
            <AlertDescription>{String(firings.error)}</AlertDescription>
          </Alert>
        )}
        {history?.length === 0 && (
          <p className="text-muted-foreground text-sm" data-testid="no-history">
            It has not fired yet.
          </p>
        )}
        <ul className="space-y-2" data-testid="history">
          {history?.map((firing) => (
            <FiringRow
              key={`${firing.at}-${firing.event_id}-${firing.outcome}`}
              firing={firing}
            />
          ))}
        </ul>
      </section>
    </div>
  );
}
