"use client";

import { use } from "react";

import { WorkflowDetail } from "@/components/workspace/workflows/workflow-detail";

export default function WorkflowDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  return <WorkflowDetail workflowId={id} />;
}
