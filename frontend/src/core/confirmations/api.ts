import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";
import { safeField, safeLines } from "@/core/display/safe";

import type { PendingList, ResolveResult } from "./types";

export async function loadPending(): Promise<PendingList> {
  const response = await fetch(`${getBackendBaseURL()}/api/confirmations`);
  const list = (await response.json()) as PendingList;
  // Every card (chat, Home's "Waiting on you") reads these fields from here:
  // made safe to display once, in this one place (core/display/safe).
  return {
    ...list,
    actions: (list.actions ?? []).map((action) => ({
      ...action,
      plan_text: safeLines(action.plan_text),
      targets: (action.targets ?? []).map((t) => safeField(t)),
      origin_label:
        action.origin_label == null
          ? action.origin_label
          : safeField(action.origin_label),
      arguments_display:
        action.arguments_display == null
          ? action.arguments_display
          : Object.fromEntries(
              Object.entries(action.arguments_display).map(([k, v]) => [
                k,
                safeField(v),
              ]),
            ),
    })),
  };
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

/** The user edits the stated plan and confirms the edit (Feature 005). The
 *  original is superseded and never runs; the edit is stated anew and
 *  confirmed in one step. */
export async function editAndConfirm(
  id: string,
  args: Record<string, unknown>,
  typedCount?: number,
): Promise<ResolveResult> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/confirmations/${id}/edit`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        arguments: args,
        typed_count: typedCount ?? null,
      }),
    },
  );
  return response.json() as Promise<ResolveResult>;
}

export interface ApplyAllResult {
  write_id: string | null;
  results: ResolveResult[];
  /** A group of outbound calls: the run in which the lead carries on with
   *  their results, when one was started. */
  resume_run_id?: string | null;
}

/** "Apply all" on a group of cards: each is confirmed by this click. For
 *  ledger suggestions every write carries one write id, so one Undo reverts
 *  them; for a turn's outbound calls each runs once and the lead resumes. */
export async function applyAll(ids: string[]): Promise<ApplyAllResult> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/confirmations/apply-all`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids }),
    },
  );
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as {
      detail?: string;
    };
    throw new Error(body.detail ?? `HTTP ${response.status}`);
  }
  return response.json() as Promise<ApplyAllResult>;
}

/** The run a confirmation started for the lead to carry on in, if any. */
export function resumeRunId(detail: Record<string, unknown> | undefined) {
  const id = detail?.resume_run_id;
  return typeof id === "string" && id ? id : null;
}
