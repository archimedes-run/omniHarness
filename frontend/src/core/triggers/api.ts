import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type { FiringsView, RulesView } from "./types";

export async function loadRules(): Promise<RulesView> {
  const response = await fetch(`${getBackendBaseURL()}/api/triggers/rules`);
  return response.json() as Promise<RulesView>;
}

export async function loadFirings(): Promise<FiringsView> {
  const response = await fetch(`${getBackendBaseURL()}/api/triggers/firings`);
  return response.json() as Promise<FiringsView>;
}
