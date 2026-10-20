"use client";

import { useParams } from "next/navigation";

import { AutomationsPage } from "@/components/workspace/automations/automations-page";

/** One automation, by its own link: its history, editor and switch. */
export default function Page() {
  const { ruleId } = useParams<{ ruleId: string }>();
  return (
    <AutomationsPage
      selection={{ kind: "rule", id: decodeURIComponent(ruleId) }}
    />
  );
}
