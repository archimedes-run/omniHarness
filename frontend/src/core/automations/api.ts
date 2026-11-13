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
  /** Feature 006-F: the custom agent it runs as; absent is the lead. */
  agent?: string | null;
  /** Feature 006-F: whether Home shows its upcoming runs and results. */
  show_on_home?: boolean;
}

export interface Template {
  template: string;
  title: string;
  description: string;
  rule: RuleDoc;
}

/** The engine's reason, shown inline: an invalid edit is refused (422), a
 * stale one too (409), and the rules in force are untouched either way. */
export class RuleEditError extends Error {
  constructor(
    message: string,
    readonly status = 0,
  ) {
    super(message);
  }
}

/** One version of one rule in the versioned config store (Spec 010). */
export interface RuleVersion {
  version: number;
  at: string;
  who: string;
  /** manual, chat, undo, existing (a baseline: the rule as it already was). */
  source: string;
  /** page, studio, chat, agent-deleted; hand-edit for a recorded hand edit. */
  via: string;
  changed: string[];
  deleted: boolean;
}

export interface RuleVersions {
  rule_id: string;
  /** Send back as base_version. */
  current: number;
  /** The file holds a hand edit not yet recorded (it is version `current`). */
  unrecorded: boolean;
  /** Whether the rule is in the rules file now. */
  exists: boolean;
  /** Version 0 may be restored: undoing the create deletes the rule. */
  can_undo_create: boolean;
  /** Newest first. */
  versions: RuleVersion[];
}

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
      response.status,
    );
  }
  return response.json() as Promise<{ version: string }>;
}

const versionsPath = (id: string) =>
  `${getBackendBaseURL()}/api/automations/rules/${encodeURIComponent(id)}`;

/** One rule's version history, newest first. 404: no such rule, no history. */
export async function loadRuleVersions(id: string): Promise<RuleVersions> {
  const response = await fetch(`${versionsPath(id)}/versions`);
  if (!response.ok) {
    throw new RuleEditError(`versions: ${response.status}`, response.status);
  }
  return response.json() as Promise<RuleVersions>;
}

/** Restore `toVersion` as a new version (0 undoes the create: deletes the
 * rule). Refused (409) when the rule changed since `baseVersion`. The same
 * route and store path the chat builder will use. */
export async function undoRule(
  id: string,
  toVersion: number,
  baseVersion: number,
  via: "page" | "studio",
): Promise<RuleVersions> {
  const response = await fetch(`${versionsPath(id)}/undo`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      to_version: toVersion,
      base_version: baseVersion,
      via,
    }),
  });
  if (!response.ok) {
    const detail = await response
      .json()
      .then((d: { detail?: unknown }) => d.detail)
      .catch(() => null);
    throw new RuleEditError(
      typeof detail === "string"
        ? detail
        : `Not restored (${response.status}).`,
      response.status,
    );
  }
  return response.json() as Promise<RuleVersions>;
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
