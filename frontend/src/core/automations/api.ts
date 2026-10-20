import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

/** A rule as the rule file holds it (app/trigger_engine/config.py). */
export interface RuleDoc {
  id: string;
  /** Display name; the id stays the key. */
  name?: string;
  type: string;
  enabled: boolean;
  match: Record<string, unknown>;
  prompt: string;
  destination: string;
  urgent?: boolean;
}

export interface Template {
  template: string;
  title: string;
  description: string;
  rule: RuleDoc;
}

/** The engine's reason, shown inline: an invalid edit is refused (422), a
 * stale one too (409), and the rules in force are untouched either way. */
export class RuleEditError extends Error {}

async function write(
  path: string,
  method: string,
  body?: unknown,
): Promise<{ version: string }> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/automations${path}`,
    {
      method,
      headers: { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    },
  );
  if (!response.ok) {
    const detail = await response
      .json()
      .then((d: { detail?: unknown }) => d.detail)
      .catch(() => null);
    throw new RuleEditError(
      typeof detail === "string"
        ? detail
        : `The change was not saved (${response.status}).`,
    );
  }
  return response.json() as Promise<{ version: string }>;
}

export const createRule = (rule: RuleDoc, version: string) =>
  write("/rules", "POST", { rule, version });
export const replaceRule = (rule: RuleDoc, version: string) =>
  write(`/rules/${encodeURIComponent(rule.id)}`, "PUT", { rule, version });
export const setRuleEnabled = (id: string, enabled: boolean, version: string) =>
  write(`/rules/${encodeURIComponent(id)}/enabled`, "PATCH", {
    enabled,
    version,
  });
export const deleteRule = (id: string, version: string) =>
  write(
    `/rules/${encodeURIComponent(id)}?version=${encodeURIComponent(version)}`,
    "DELETE",
  );

export async function loadTemplates(): Promise<Template[]> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/automations/templates`,
  );
  if (!response.ok) throw new Error(`templates: ${response.status}`);
  return response.json() as Promise<Template[]>;
}
