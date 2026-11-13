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
  duration_s?: number;
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
