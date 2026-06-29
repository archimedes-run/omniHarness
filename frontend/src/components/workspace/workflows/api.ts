import { fetch } from "@/core/api/fetcher";
import type { RunMessage } from "@/core/threads/types";

import type {
  Workflow,
  WorkflowArtifactLink,
  WorkflowRun,
  WorkflowSpec,
} from "./types";

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let msg = `Request failed: ${res.status}`;
    try {
      const body = (await res.json()) as { detail?: string; message?: string };
      msg = body.detail ?? body.message ?? msg;
    } catch {
      /* ignore parse error */
    }
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return res.json() as Promise<T>;
}

export async function listWorkflows(): Promise<Workflow[]> {
  const res = await fetch("/api/workflows");
  return handleResponse<Workflow[]>(res);
}

export async function getWorkflow(id: string): Promise<Workflow> {
  const res = await fetch(`/api/workflows/${id}`);
  return handleResponse<Workflow>(res);
}

export async function createWorkflow(data: {
  title: string;
  description?: string;
  instruction_prompt?: string;
}): Promise<Workflow> {
  const res = await fetch("/api/workflows", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  return handleResponse<Workflow>(res);
}

export async function patchWorkflow(
  id: string,
  data: Partial<{ title: string; description: string; status: string }>,
): Promise<Workflow> {
  const res = await fetch(`/api/workflows/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  return handleResponse<Workflow>(res);
}

export async function archiveWorkflow(id: string): Promise<Workflow> {
  return patchWorkflow(id, { status: "archived" });
}

export async function generateSpec(id: string): Promise<WorkflowSpec> {
  const res = await fetch(`/api/workflows/${id}/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  return handleResponse<WorkflowSpec>(res);
}

export async function triggerRun(id: string): Promise<WorkflowRun> {
  const res = await fetch(`/api/workflows/${id}/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  return handleResponse<WorkflowRun>(res);
}

export async function listRuns(id: string): Promise<WorkflowRun[]> {
  const res = await fetch(`/api/workflows/${id}/runs`);
  return handleResponse<WorkflowRun[]>(res);
}

export async function getRun(
  workflowId: string,
  runId: string,
): Promise<WorkflowRun> {
  const res = await fetch(`/api/workflows/${workflowId}/runs/${runId}`);
  return handleResponse<WorkflowRun>(res);
}

export async function cancelRun(
  workflowId: string,
  runId: string,
): Promise<WorkflowRun> {
  const res = await fetch(`/api/workflows/${workflowId}/runs/${runId}/cancel`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  return handleResponse<WorkflowRun>(res);
}

export async function retryRun(
  workflowId: string,
  runId: string,
): Promise<WorkflowRun> {
  const res = await fetch(`/api/workflows/${workflowId}/runs/${runId}/retry`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  return handleResponse<WorkflowRun>(res);
}

export async function listRunArtifacts(
  workflowId: string,
  runId: string,
): Promise<WorkflowArtifactLink[]> {
  const res = await fetch(
    `/api/workflows/${workflowId}/runs/${runId}/artifacts`,
  );
  return handleResponse<WorkflowArtifactLink[]>(res);
}

export async function getRunMessages(
  threadId: string,
  runId: string,
): Promise<{ data: RunMessage[]; has_more: boolean }> {
  const res = await fetch(`/api/threads/${threadId}/runs/${runId}/messages`);
  return handleResponse<{ data: RunMessage[]; has_more: boolean }>(res);
}
