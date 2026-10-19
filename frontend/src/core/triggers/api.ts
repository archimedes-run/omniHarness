import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type { FiringsView, RulesView } from "./types";

// A failed read throws, so the page shows "I cannot read the trigger records"
// rather than treating an error body as data.
async function read<T>(path: string): Promise<T> {
  const response = await fetch(`${getBackendBaseURL()}${path}`);
  if (!response.ok) throw new Error(`${path}: ${response.status}`);
  return response.json() as Promise<T>;
}

export const loadRules = () => read<RulesView>("/api/triggers/rules");
export const loadFirings = () => read<FiringsView>("/api/triggers/firings");
