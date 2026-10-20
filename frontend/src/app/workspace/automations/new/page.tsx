"use client";

import { useSearchParams } from "next/navigation";

import { AutomationsPage } from "@/components/workspace/automations/automations-page";
import { useAutomationTemplates } from "@/core/automations/hooks";

/** A new automation: blank, or from a template named by ?template=. */
export default function Page() {
  const slug = useSearchParams().get("template");
  const { templates } = useAutomationTemplates();
  const template = templates?.find((t) => t.template === slug);
  return <AutomationsPage selection={{ kind: "new", template }} />;
}
