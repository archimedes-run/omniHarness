import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type { SessionsView } from "./types";

export async function loadSessions(): Promise<SessionsView> {
  const response = await fetch(`${getBackendBaseURL()}/api/sessions`);
  return response.json() as Promise<SessionsView>;
}
