import { fetch } from "../api/fetcher";
import { getBackendBaseURL } from "../config";

/** Spec 009 Slice 1: a coding job (OpenCode in the container sandbox). */
export type CodeJobStatus =
  | "running"
  | "verified"
  | "unverified"
  | "failed"
  | "stopped"
  | "blocked";

export interface CodeJobCommand {
  command: string;
  exit_code: number | null;
  status?: string;
  is_test?: boolean;
  is_build?: boolean;
}

/** The system's layout check of a built web app (a headless browser at each
 * width). `error`: the check itself could not run, never counted. */
export interface CodeJobLayout {
  outcome: "pass" | "fail" | "error";
  widths: number[];
  mode: "enforce" | "warn";
  /** Each failure as shown, element names and error text included. */
  failures: string[];
  /** The failures in the system's own words (the job's reason). */
  summary?: string[];
  warnings: string[];
  /** The system's wording for why there is no answer (a fixed set). */
  error: string | null;
  error_code?: string | null;
  /** That no-answer counts against "verified" (its result could not be read). */
  counted?: boolean;
  seconds?: number;
}

/** A screenshot of an app's mock build (Spec 011 FR-026), in the thread's outputs. */
export interface CodeJobAppShot {
  theme: "light" | "dark";
  width: number;
  path: string;
}

/** The system's checks of an app-mode job's mock build (Spec 011 FR-026). */
export interface CodeJobAppChecks {
  outcome: "pass" | "fail" | "error";
  /** The failures in the system's own words. */
  summary?: string[];
  /** Each failure as shown, element and file names from the page included. */
  failures?: string[];
  /** What the system measured but does not block on (small text, targets). */
  design?: string[];
  error?: string | null;
  bundle?: { bytes: number; limit: number } | null;
  shots?: CodeJobAppShot[];
}

/** An app the gateway registered from a verified app-mode job (FR-028). */
export interface CodeJobAppRegistration {
  app_id: string;
  version: number;
  name: string;
  needs_approval: boolean;
  suggestion?: boolean;
  url: string;
}

export interface CodeJobResult {
  status: CodeJobStatus;
  reason: string | null;
  verify?: {
    command: string;
    exit_code: number | null;
    timed_out?: boolean;
    limit_s?: number;
    seconds?: number;
    log_tail?: string;
  } | null;
  expected_files?: { path: string; exists: boolean; bytes: number }[];
  layout?: CodeJobLayout | null;
  files_changed?: {
    added: string[];
    modified: string[];
    deleted: string[];
    count: number;
  };
  worker?: {
    exit_code: number | null;
    commands: number;
    failed_commands: CodeJobCommand[];
    tests: CodeJobCommand[];
    builds: CodeJobCommand[];
    errors: string[];
    summary: string;
  };
  cost_usd?: number;
  budget_usd?: number;
  calls?: number;
  over_reservation_calls?: number;
  model?: string;
  published?: { artifact_id: string; path: string } | null;
  /** This job is the one automatic fix of that job's layout failures, or
   * one of an app's design passes. */
  fix_of?: string | null;
  duration_s?: number;
  /** App mode (Spec 011). */
  app?: { root: string; design_pass?: boolean } | null;
  app_checks?: CodeJobAppChecks | null;
  app_registration?: CodeJobAppRegistration | null;
  app_registration_error?: { code: string; message: string } | null;
  design_passes_used?: number;
}

export interface CodeJob {
  id: string;
  thread_id: string;
  tool_call_id: string;
  title: string;
  project_dir: string;
  model: string;
  status: CodeJobStatus;
  phase: string;
  budget_usd: number;
  spent_usd: number;
  calls: number;
  stop_requested: boolean;
  reason: string | null;
  result: CodeJobResult | null;
  created_at: string;
  updated_at: string;
  finished_at: string | null;
}

export type CodeJobStep =
  | { seq: number; at: string; kind: "phase"; phase: string; text: string }
  | {
      seq: number;
      at: string;
      kind: "command";
      command: string;
      exit_code: number | null;
      status: string;
      output: string;
      is_test?: boolean;
      is_build?: boolean;
    }
  | {
      seq: number;
      at: string;
      kind: "file";
      action: string;
      path: string;
      status: string;
      error?: string | null;
    }
  | {
      seq: number;
      at: string;
      kind: "tool";
      tool: string;
      title: string;
      status: string;
    }
  | { seq: number; at: string; kind: "message"; text: string }
  | { seq: number; at: string; kind: "error"; message: string }
  | {
      seq: number;
      at: string;
      kind: "verify";
      command: string;
      exit_code: number | null;
      timed_out: boolean;
      output: string;
    }
  | {
      seq: number;
      at: string;
      kind: "check";
      path: string;
      exists: boolean;
      bytes: number;
    }
  | ({ seq: number; at: string; kind: "layout" } & CodeJobLayout)
  | {
      seq: number;
      at: string;
      kind: "app_checks";
      outcome: "pass" | "fail" | "error";
      summary: string[];
      design_count: number;
      error: string | null;
      bundle: { bytes: number; limit: number } | null;
      shots: CodeJobAppShot[];
    }
  | ({
      seq: number;
      at: string;
      kind: "app_registered";
    } & CodeJobAppRegistration)
  | {
      seq: number;
      at: string;
      kind: "published";
      artifact_id: string;
      path: string;
    };

export interface CodeJobPayload {
  job: CodeJob;
  steps: CodeJobStep[];
  month: { spent_usd: number; cap_usd: number | null };
}

export class CodeJobNotFound extends Error {}

export async function loadCodeJobByCall({
  threadId,
  toolCallId,
  after,
}: {
  threadId: string;
  toolCallId: string;
  after: number;
}): Promise<CodeJobPayload> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}/code-jobs/by-call/${encodeURIComponent(toolCallId)}?after=${after}`,
  );
  if (response.status === 404) {
    throw new CodeJobNotFound("not started");
  }
  if (!response.ok) {
    throw new Error(`Failed to load the coding job: ${response.status}`);
  }
  return response.json() as Promise<CodeJobPayload>;
}

export async function stopCodeJob({
  threadId,
  jobId,
}: {
  threadId: string;
  jobId: string;
}): Promise<{ stopping: boolean; job: CodeJob | null }> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}/code-jobs/${encodeURIComponent(jobId)}/stop`,
    { method: "POST" },
  );
  if (!response.ok) {
    throw new Error(`Failed to stop the coding job: ${response.status}`);
  }
  return response.json() as Promise<{ stopping: boolean; job: CodeJob | null }>;
}
