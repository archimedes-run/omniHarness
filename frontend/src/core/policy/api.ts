import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type { RulesInForce, Tier3Execution, TierCheck } from "./types";

export async function loadRules(): Promise<RulesInForce> {
  const response = await fetch(`${getBackendBaseURL()}/api/policy/rules`);
  return response.json() as Promise<RulesInForce>;
}

export async function checkTier(
  tool: string,
  args: string,
): Promise<TierCheck> {
  const query = new URLSearchParams({ tool, args: args.trim() || "{}" });
  const response = await fetch(
    `${getBackendBaseURL()}/api/policy/explain?${query.toString()}`,
  );
  if (!response.ok) throw new Error(await response.text());
  return response.json() as Promise<TierCheck>;
}

export async function loadAudit(): Promise<Tier3Execution[]> {
  const response = await fetch(`${getBackendBaseURL()}/api/policy/audit`);
  return response.json() as Promise<Tier3Execution[]>;
}
