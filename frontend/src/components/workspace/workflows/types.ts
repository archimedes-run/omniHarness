export interface WorkflowSpecStep {
  title: string;
  description: string;
  suggested_tools: string[];
}

export interface WorkflowSpec {
  title: string;
  description: string;
  steps: WorkflowSpecStep[];
  required_capabilities: string[];
  risks: string[];
  approval_policy: string;
}

export interface Workflow {
  id: string;
  owner_id: string | null;
  title: string;
  description: string | null;
  status: string; // draft | active | archived
  instruction_prompt?: string | null;
  current_version_id: string | null;
  spec_json?: WorkflowSpec | null;
  created_at: string;
  updated_at: string;
}

export interface WorkflowRun {
  id: string;
  workflow_id: string;
  trigger_type: string;
  trigger_payload: Record<string, unknown> | null;
  status: string; // queued | running | succeeded | failed | canceled | expired
  started_at: string | null;
  completed_at: string | null;
  error_summary: string | null;
  thread_id: string | null;
  run_id: string | null; // underlying LangGraph run ID
  idempotency_key: string;
  initiated_by: string | null;
  source_run_id: string | null; // set when this is a retry
  final_summary: string | null; // only on GET /runs/{id} when succeeded
  created_at: string;
  updated_at: string;
}
