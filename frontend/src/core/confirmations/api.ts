import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type { PendingList, ResolveResult } from "./types";

export async function loadPending(): Promise<PendingList> {
  const response = await fetch(`${getBackendBaseURL()}/api/confirmations`);
  return response.json() as Promise<PendingList>;
}

async function resolve(
  id: string,
  action: "confirm" | "decline",
  typedCount?: number,
): Promise<ResolveResult> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/confirmations/${id}/${action}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ typed_count: typedCount ?? null }),
    },
  );
  return response.json() as Promise<ResolveResult>;
}

export const confirmAction = (id: string, typedCount?: number) =>
  resolve(id, "confirm", typedCount);
export const declineAction = (id: string) => resolve(id, "decline");
