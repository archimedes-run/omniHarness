/**
 * An agent's tool choice as Configuration -> Integrations edits it (006-G).
 *
 * The SERVER enforces the allowlist (`AgentConfig.tools`, applied where every
 * run's tools are assembled); this module only turns it into ticks and back.
 * Two rules matter:
 *
 *  * A choice the catalog cannot show right now (a server that is down, an
 *    app since disconnected) is KEPT on save, never silently dropped.
 *  * An agent saved before 006-G has no allowlist and keeps its tool groups.
 *    Its ticks are derived for display only; nothing is written for it unless
 *    the person changes a tick.
 */

import type { AgentTools } from "@/core/agents";

import type { CatalogIntegration, ToolCatalog } from "./types";

/** integration id -> the tool names ticked in it. */
export type Selection = Record<string, string[]>;

/** The MCP servers every chat gets (persistence/thread_tool_selection). */
export const PINNED_LOCAL = ["filesystem", "postgres", "session-watcher"];

export function usable(i: CatalogIntegration): boolean {
  return i.status === "connected" && i.tools.length > 0;
}

/** The ticks an allowlist means, for the integrations the catalog shows. */
export function selectionOf(
  tools: AgentTools,
  catalog: ToolCatalog,
): Selection {
  const allowed = new Set(tools.tools);
  const out: Selection = {};
  for (const integration of catalog.integrations) {
    if (!tools.integrations.includes(integration.id)) continue;
    const on = integration.tools
      .filter((t) => allowed.has(t.name))
      .map((t) => t.name);
    if (on.length) out[integration.id] = on;
  }
  return out;
}

/** What an agent with no allowlist gets today, as ticks (display only). */
export function legacySelection(
  toolGroups: string[] | null,
  catalog: ToolCatalog,
): Selection {
  const out: Selection = {};
  for (const i of catalog.integrations) {
    if (!usable(i)) continue;
    const inGroups =
      i.kind === "builtin" &&
      (i.id === "builtin:ledger" ||
        i.id === "builtin:workspace" ||
        toolGroups === null ||
        toolGroups.includes(i.id.slice("builtin:".length)));
    const pinned =
      i.kind !== "builtin" &&
      i.kind !== "app" &&
      PINNED_LOCAL.includes(i.id.slice("local:".length));
    if (inGroups || pinned) out[i.id] = i.tools.map((t) => t.name);
  }
  return out;
}

/** The allowlist to save: the ticks, plus every earlier choice the catalog
 * cannot show now (an integration that is down or disconnected, and tools no
 * shown integration lists), kept exactly as it was. */
export function allowlistOf(
  selection: Selection,
  catalog: ToolCatalog,
  previous: AgentTools | null,
): AgentTools {
  const shown = new Map(catalog.integrations.map((i) => [i.id, i]));
  const listed = new Set(
    catalog.integrations
      .filter(usable)
      .flatMap((i) => i.tools.map((t) => t.name)),
  );
  const integrations = new Set<string>();
  const names = new Set<string>();
  for (const [id, tools] of Object.entries(selection)) {
    if (!tools.length) continue;
    integrations.add(id);
    tools.forEach((t) => names.add(t));
  }
  for (const id of previous?.integrations ?? []) {
    const now = shown.get(id);
    if (!now || !usable(now)) integrations.add(id);
  }
  for (const t of previous?.tools ?? []) if (!listed.has(t)) names.add(t);
  return { integrations: [...integrations].sort(), tools: [...names].sort() };
}

/** A drafted integration: its tools that do not ask first, ticked for review.
 * Tools that ask first are left for the person to tick. */
export function draftedSelection(
  ids: string[],
  catalog: ToolCatalog,
): Selection {
  const out: Selection = {};
  for (const id of ids) {
    const i = catalog.integrations.find((x) => x.id === id);
    if (!i || !usable(i)) continue;
    const on = i.tools
      .filter((t) => t.tier !== null && t.tier < 3)
      .map((t) => t.name);
    if (on.length) out[id] = on;
  }
  return out;
}

export function countSelection(selection: Selection): {
  integrations: number;
  tools: number;
} {
  const lists = Object.values(selection).filter((l) => l.length > 0);
  return {
    integrations: lists.length,
    tools: lists.reduce((n, l) => n + l.length, 0),
  };
}

/** The Tier 3 tools ticked: these always wait for the person. */
export function asksFirst(
  selection: Selection,
  catalog: ToolCatalog | undefined,
): { integration: CatalogIntegration; label: string; name: string }[] {
  if (!catalog) return [];
  const out: {
    integration: CatalogIntegration;
    label: string;
    name: string;
  }[] = [];
  for (const i of catalog.integrations) {
    const on = new Set(selection[i.id] ?? []);
    for (const t of i.tools)
      if (t.tier === 3 && on.has(t.name))
        out.push({ integration: i, label: t.label, name: t.name });
  }
  return out;
}

export function sameSelection(a: Selection, b: Selection): boolean {
  const norm = (s: Selection) =>
    JSON.stringify(
      Object.entries(s)
        .filter(([, v]) => v.length)
        .map(([k, v]) => [k, [...v].sort()])
        .sort(([x], [y]) => String(x).localeCompare(String(y))),
    );
  return norm(a) === norm(b);
}
