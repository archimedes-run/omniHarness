/**
 * The Agent stepper's working copy (006-G): what each step edits, what is
 * unsaved per step, and the writes a Save makes. Pure, so it is unit-tested.
 */

import type { Agent, AgentNotify, AgentTools } from "@/core/agents";
import type { AgentSchedule, ScheduleWrite } from "@/core/studio";
import { sameSelection, type Selection } from "@/core/studio/tool-select";

export interface SchedRow {
  /** Local key (rule id when saved). */
  key: string;
  ruleId: string | null;
  cron: string;
  timezone: string;
  prompt: string;
  name: string;
  telegram: boolean;
  home: boolean;
  enabled: boolean;
  nextRun: string | null;
  heldUntil: string | null;
}

export interface AgentForm {
  avatar: string;
  name: string;
  /** The one sentence: the agent's description. */
  sentence: string;
  instructions: string;
  /** null until the tool catalog is loaded. */
  selection: Selection | null;
  /** An agent with no allowlist gets one only when a tick changes. */
  toolsTouched: boolean;
  /** null: every enabled skill (agents saved that way). */
  skills: string[] | null;
  grants: string[];
  schedules: SchedRow[];
  notify: AgentNotify;
}

export const STEP_FIELDS: Record<number, (keyof AgentForm)[]> = {
  1: ["avatar", "name", "sentence", "instructions"],
  2: ["selection", "skills", "grants"],
  3: ["schedules"],
  4: ["notify"],
};

const sortedJson = (v: unknown) =>
  JSON.stringify(Array.isArray(v) ? [...v].sort() : v);

function fieldDirty(
  form: AgentForm,
  orig: AgentForm,
  key: keyof AgentForm,
): boolean {
  if (key === "selection") {
    if (!form.toolsTouched || !form.selection || !orig.selection) return false;
    return !sameSelection(form.selection, orig.selection);
  }
  if (key === "grants")
    return sortedJson(form.grants) !== sortedJson(orig.grants);
  if (key === "schedules")
    return schedulesKey(form.schedules) !== schedulesKey(orig.schedules);
  return JSON.stringify(form[key]) !== JSON.stringify(orig[key]);
}

function schedulesKey(rows: SchedRow[]): string {
  return JSON.stringify(
    rows.map((r) => [
      r.ruleId,
      r.cron,
      r.timezone,
      r.prompt,
      r.telegram,
      r.home,
      r.enabled,
    ]),
  );
}

export function stepDirty(
  form: AgentForm,
  orig: AgentForm,
  step: number,
): boolean {
  return STEP_FIELDS[step]!.some((k) => fieldDirty(form, orig, k));
}

export function anyDirty(form: AgentForm, orig: AgentForm): boolean {
  return [1, 2, 3, 4].some((n) => stepDirty(form, orig, n));
}

export function rowsOf(schedules: AgentSchedule[]): SchedRow[] {
  return schedules.map((s) => ({
    key: s.rule_id,
    ruleId: s.rule_id,
    cron: s.schedule,
    timezone: s.timezone,
    prompt: s.prompt,
    name: s.name,
    telegram: s.telegram,
    home: s.show_on_home,
    enabled: s.enabled,
    nextRun: s.next_run,
    heldUntil: s.held_until,
  }));
}

/** The agents-API fields a save sends (create, or the changed ones on edit). */
export function agentFields(
  form: AgentForm,
  orig: AgentForm | null,
  tools: AgentTools | null,
) {
  const out: Record<string, unknown> = {};
  const changed = (k: keyof AgentForm) => !orig || fieldDirty(form, orig, k);
  if (changed("name")) out.display_name = form.name.trim() || null;
  if (changed("sentence")) out.description = form.sentence.trim();
  if (changed("instructions")) out.soul = form.instructions;
  if (changed("avatar")) out.avatar = form.avatar;
  if (changed("skills")) out.skills = form.skills;
  if (changed("notify")) out.notify = form.notify;
  if (tools && (!orig || changed("selection"))) out.tools = tools;
  return out;
}

export type SchedChange =
  | { kind: "create"; body: Omit<ScheduleWrite, "version"> }
  | { kind: "update"; ruleId: string; body: Omit<ScheduleWrite, "version"> }
  | { kind: "delete"; ruleId: string };

/** The schedule writes that turn `orig` into `form` (006-F routes). */
export function scheduleChanges(
  form: SchedRow[],
  orig: SchedRow[],
): SchedChange[] {
  const body = (r: SchedRow) => ({
    schedule: r.cron,
    timezone: r.timezone,
    telegram: r.telegram,
    show_on_home: r.home,
    prompt: r.prompt.trim() || null,
    name: r.name || null,
    enabled: r.enabled,
  });
  const out: SchedChange[] = [];
  const byId = new Map(orig.filter((r) => r.ruleId).map((r) => [r.ruleId!, r]));
  for (const row of form) {
    if (!row.ruleId) {
      out.push({ kind: "create", body: body(row) });
      continue;
    }
    const before = byId.get(row.ruleId);
    if (before && schedulesKey([before]) !== schedulesKey([row]))
      out.push({ kind: "update", ruleId: row.ruleId, body: body(row) });
  }
  const kept = new Set(form.map((r) => r.ruleId).filter(Boolean));
  for (const id of byId.keys())
    if (!kept.has(id)) out.push({ kind: "delete", ruleId: id });
  return out;
}

/** The form for a saved agent (selection filled in once the catalog loads). */
export function formOf(
  agent: Agent,
  avatar: string,
  grants: string[],
  schedules: SchedRow[],
): AgentForm {
  return {
    avatar,
    name: agent.display_name?.trim() ?? "",
    sentence: agent.description ?? "",
    instructions: agent.soul ?? "",
    selection: null,
    toolsTouched: false,
    skills: agent.skills,
    grants,
    schedules,
    notify: agent.notify ?? { telegram: true, home: true },
  };
}
