import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

/** What a scheduled run did on its own under standing grants (Feature 006). */
export interface RunWrite {
  at: string;
  tool: string;
  classes: string[];
  targets: string[];
  /** "from: email “…”", "from: page “…”" or the schedule's own prompt;
   *  redacted, never the content's body. */
  source_label: string;
  write_id: string | null;
  undone: boolean;
  /** 006-G: false for a granted action the ledger did not make (an email
   * draft): listed, never undone here. Absent from older gateways: true. */
  undoable?: boolean;
}

export interface RunSummary {
  firing_id: string;
  rule_id: string | null;
  agent: string;
  writes: RunWrite[];
  all_undone: boolean;
}

export class RunSummaryError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function call(path: string, init?: RequestInit): Promise<RunSummary> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/studio${path}`,
    init,
  );
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as {
      detail?: string;
    };
    throw new RunSummaryError(
      typeof body.detail === "string" ? body.detail : `HTTP ${response.status}`,
      response.status,
    );
  }
  return response.json() as Promise<RunSummary>;
}

export const loadRunSummary = (firingId: string) =>
  call(`/runs/${encodeURIComponent(firingId)}`);

/** Undo everything this run did on its own: all or nothing. */
export const undoRun = (firingId: string) =>
  call(`/runs/${encodeURIComponent(firingId)}/undo`, { method: "POST" });
