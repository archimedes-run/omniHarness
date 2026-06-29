"use client";

import { use } from "react";

import { RunTimeline } from "@/components/workspace/workflows/run-timeline";

export default function RunTimelinePage({
  params,
}: {
  params: Promise<{ id: string; run_id: string }>;
}) {
  const { id, run_id } = use(params);
  return <RunTimeline workflowId={id} runId={run_id} />;
}
