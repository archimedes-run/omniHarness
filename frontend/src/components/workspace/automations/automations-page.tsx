"use client";

import { useRouter } from "next/navigation";

import { WorkflowList } from "@/components/workspace/workflows/workflow-list";
import { useAutomationTemplates } from "@/core/automations/hooks";
import { env } from "@/env";

import {
  AutomationsBoard,
  type AutomationSelection,
} from "./automations-board";

/**
 * Automations as a page: the same board as the capsule panel, with the
 * selection in the URL (/workspace/automations/<id>, /workspace/automations/new)
 * so each automation has a link of its own. Workflows follow, behind their flag.
 */
export function AutomationsPage({
  selection,
}: {
  selection: AutomationSelection;
}) {
  const router = useRouter();
  const { templates } = useAutomationTemplates();
  const go = (next: AutomationSelection) => {
    if (!next) router.push("/workspace/automations");
    else if (next.kind === "rule")
      router.push(`/workspace/automations/${encodeURIComponent(next.id)}`);
    else
      router.push(
        next.template
          ? `/workspace/automations/new?template=${next.template.template}`
          : "/workspace/automations/new",
      );
  };
  return (
    <div className="flex w-full flex-col">
      <h1 className="sr-only">Automations</h1>
      <AutomationsBoard
        selection={selection}
        onSelect={go}
        templates={templates}
      />
      {env.NEXT_PUBLIC_FEATURE_WORKFLOWS === "true" && (
        <section
          className="border-border flex flex-col gap-2 border-t p-6"
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
