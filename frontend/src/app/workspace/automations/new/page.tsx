"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { RuleForm } from "@/components/workspace/automations/rule-form";
import { useAutomationTemplates } from "@/core/automations/hooks";
import { useTriggerRules } from "@/core/triggers/hooks";

export default function NewAutomationPage() {
  const slug = useSearchParams().get("template");
  const router = useRouter();
  const { templates } = useAutomationTemplates();
  const { view } = useTriggerRules();
  const template = templates?.find((t) => t.template === slug);
  // A free id: the template's, or with a number if that is taken.
  const taken = new Set(view?.rules.map((r) => r.id));
  let id = template?.rule.id ?? "";
  for (let n = 2; taken.has(id); n++) id = `${template?.rule.id}-${n}`;

  return (
    <div className="mx-auto w-full max-w-3xl space-y-6 p-6">
      <header className="space-y-1">
        <Link
          href="/workspace/automations"
          className="text-muted-foreground text-sm hover:underline"
        >
          ← Automations
        </Link>
        <h1 className="text-xl font-semibold">
          New automation{template ? `: ${template.title}` : ""}
        </h1>
        {template && (
          <p className="text-muted-foreground text-sm">
            {template.description}
          </p>
        )}
      </header>
      {templates && !template && (
        <Alert data-testid="no-template">
          <AlertTitle>Pick a starting point</AlertTitle>
          <AlertDescription>
            Choose a template on the Automations page.
          </AlertDescription>
        </Alert>
      )}
      {template && view && (
        <RuleForm
          mode="create"
          version={view.version}
          writable={view.writable}
          initial={{ ...template.rule, id }}
          onSaved={(saved) =>
            router.push(`/workspace/automations/${encodeURIComponent(saved)}`)
          }
        />
      )}
    </div>
  );
}
