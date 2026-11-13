"use client";

import { useParams } from "next/navigation";

import { TraceView } from "@/components/workspace/traces/trace-view";

/** One run's trace (spec 009 FR-084): reached from a chat answer's "Open
 * trace" and from Settings → Activity log's chat traces. */
export default function TracePage() {
  const { run_id } = useParams<{ run_id: string }>();
  return <TraceView runId={decodeURIComponent(run_id)} />;
}
