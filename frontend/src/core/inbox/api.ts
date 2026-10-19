import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type { InboxAlerts } from "./types";

export async function loadInboxAlerts(): Promise<InboxAlerts> {
  const response = await fetch(`${getBackendBaseURL()}/api/inbox/alerts`);
  if (!response.ok) {
    throw new Error(`alerts could not be read: ${response.status}`);
  }
  return response.json() as Promise<InboxAlerts>;
}
