"use client";

import { useParams } from "next/navigation";

import { RunSummaryView } from "@/components/workspace/runs/run-summary";

export default function RunSummaryPage() {
  const { firing_id } = useParams<{ firing_id: string }>();
  return (
    <div className="mx-auto w-full max-w-3xl p-6">
      <RunSummaryView firingId={firing_id} />
    </div>
  );
}
