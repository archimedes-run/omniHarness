import { useQuery } from "@tanstack/react-query";

import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";
import type { RunDetail, RunSummary } from "@/core/run-history/api";
import {
  parseVerification,
  type VerificationRecord,
} from "@/core/verification";

/** Mirrors the backend's chat-run trace (spec 009 FR-080, kind "chat"). */
export type StepType =
  | "checklist"
  | "tool"
  | "card"
  | "card_resolved"
  | "resume"
  | "retry"
  | "verify"
  | "summary"
  | "subagent"
  | "reply";

export interface TraceStep {
  index: number;
  type: StepType | string;
  name: string;
  tier: 1 | 2 | 3 | null;
  status: string;
  started_at: string | null;
  ended_at: string | null;
  parent: number | null;
  source_event: string | null;
  args: string | null;
  output: string | null;
  card_id: string | null;
}

export interface Trace {
  version: number;
  run_id: string;
  thread_id: string | null;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  model: string | null;
  tokens: { input: number; output: number; total: number };
  llm_calls: number;
  cost_usd: number | null;
  resumed_from: { run_id: string | null; card_ids: string[] } | null;
  resumes: string[];
  done_criteria: string | null;
  verification: VerificationRecord | null;
  retries: number;
  steps: TraceStep[];
  cards: {
    id: string;
    tool: string;
    tier: number | null;
    outcome: string | null;
  }[];
}

export class TraceNotFound extends Error {}

function num(v: unknown, fallback = 0): number {
  return typeof v === "number" && Number.isFinite(v) ? v : fallback;
}
function str(v: unknown): string | null {
  return typeof v === "string" ? v : null;
}

/** Parse the stored body; null when the body is withheld or not a trace. */
export function parseTrace(body: unknown): Trace | null {
  if (!body || typeof body !== "object") return null;
  const t = (body as { trace?: unknown }).trace;
  if (!t || typeof t !== "object") return null;
  const o = t as Record<string, unknown>;
  const tokens = (o.tokens ?? {}) as Record<string, unknown>;
  const resumed = o.resumed_from as Record<string, unknown> | null | undefined;
  return {
    version: num(o.version, 1),
    run_id: str(o.run_id) ?? "",
    thread_id: str(o.thread_id),
    status: str(o.status) ?? "unknown",
    started_at: str(o.started_at),
    finished_at: str(o.finished_at),
    duration_ms: typeof o.duration_ms === "number" ? o.duration_ms : null,
    model: str(o.model),
    tokens: {
      input: num(tokens.input),
      output: num(tokens.output),
      total: num(tokens.total, num(tokens.input) + num(tokens.output)),
    },
    llm_calls: num(o.llm_calls),
    cost_usd: typeof o.cost_usd === "number" ? o.cost_usd : null,
    resumed_from:
      resumed && typeof resumed === "object"
        ? {
            run_id: str(resumed.run_id),
            card_ids: Array.isArray(resumed.card_ids)
              ? resumed.card_ids.filter(
                  (x): x is string => typeof x === "string",
                )
              : [],
          }
        : null,
    resumes: Array.isArray(o.resumes)
      ? o.resumes.filter((x): x is string => typeof x === "string")
      : [],
    done_criteria: str(o.done_criteria),
    verification: parseVerification(o.verification),
    retries: num(o.retries),
    steps: Array.isArray(o.steps)
      ? o.steps.flatMap((s, i): TraceStep[] => {
          if (!s || typeof s !== "object") return [];
          const x = s as Record<string, unknown>;
          const tier = x.tier;
          return [
            {
              index: num(x.index, i),
              type: str(x.type) ?? "tool",
              name: str(x.name) ?? "",
              tier: tier === 1 || tier === 2 || tier === 3 ? tier : null,
              status: str(x.status) ?? "ok",
              started_at: str(x.started_at),
              ended_at: str(x.ended_at),
              parent: typeof x.parent === "number" ? x.parent : null,
              source_event: str(x.source_event),
              args: str(x.args),
              output: str(x.output),
              card_id: str(x.card_id),
            },
          ];
        })
      : [],
    cards: Array.isArray(o.cards)
      ? o.cards.flatMap((c) => {
          if (!c || typeof c !== "object") return [];
          const x = c as Record<string, unknown>;
          return [
            {
              id: str(x.id) ?? "",
              tool: str(x.tool) ?? "",
              tier: typeof x.tier === "number" ? x.tier : null,
              outcome: str(x.outcome),
            },
          ];
        })
      : [],
  };
}

/** Is the stored body withheld (unreadable / missing blob)? */
export function withheldReason(body: unknown): string | null {
  if (body && typeof body === "object" && "withheld" in body) {
    const w = (body as { withheld?: unknown }).withheld;
    return typeof w === "string" ? w : "withheld";
  }
  return null;
}

export type StatusTone = "success" | "warning" | "danger" | "neutral";

/** One status word -> its tone. Unknown words are neutral, never success. */
export function statusTone(status: string): StatusTone {
  switch (status) {
    case "ok":
    case "executed":
    case "success":
    case "verified":
      return "success";
    case "needs_confirmation":
    case "declined":
    case "expired":
    case "interrupted":
    case "refused":
    case "unverified":
      return "warning";
    case "error":
    case "failed":
      return "danger";
    default:
      return "neutral";
  }
}

const STATUS_LABEL: Record<string, string> = {
  ok: "Done",
  error: "Failed",
  needs_confirmation: "Needs confirmation",
  refused: "Refused",
  executed: "Confirmed and ran",
  declined: "Declined",
  failed: "Failed",
  expired: "Expired",
  success: "Finished",
  interrupted: "Stopped",
};

export function statusLabel(status: string): string {
  return STATUS_LABEL[status] ?? status.replace(/_/g, " ");
}

const TYPE_LABEL: Record<string, string> = {
  checklist: "Checklist",
  tool: "Tool",
  card: "Card",
  card_resolved: "Card answered",
  resume: "Resumed",
  retry: "Retry",
  verify: "Verification",
  summary: "Summarised",
  subagent: "Subagent",
  reply: "Reply",
};

export function typeLabel(type: string): string {
  return TYPE_LABEL[type] ?? type;
}

export function formatDuration(ms: number | null): string {
  if (ms === null || ms < 0) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(s < 10 ? 1 : 0)} s`;
  const m = Math.floor(s / 60);
  return `${m} min ${Math.round(s - m * 60)} s`;
}

export function stepDuration(step: TraceStep): number | null {
  if (!step.started_at || !step.ended_at) return null;
  const d = Date.parse(step.ended_at) - Date.parse(step.started_at);
  return Number.isFinite(d) ? d : null;
}

export function formatCost(usd: number | null): string {
  if (usd === null) return "—";
  if (usd === 0) return "$0.00";
  return usd < 0.01 ? `<$0.01` : `$${usd.toFixed(2)}`;
}

export function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

/** Children of each step (by `parent`), roots under -1, in index order. */
export function stepTree(steps: TraceStep[]): Map<number, TraceStep[]> {
  const indices = new Set(steps.map((s) => s.index));
  const tree = new Map<number, TraceStep[]>();
  for (const step of [...steps].sort((a, b) => a.index - b.index)) {
    const key =
      step.parent !== null &&
      indices.has(step.parent) &&
      step.parent !== step.index
        ? step.parent
        : -1;
    tree.set(key, [...(tree.get(key) ?? []), step]);
  }
  return tree;
}

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`${getBackendBaseURL()}/api/run-history${path}`);
  if (response.status === 404) throw new TraceNotFound("not found");
  if (!response.ok) {
    const detail = await response
      .json()
      .then((d: { detail?: unknown }) => d.detail)
      .catch(() => null);
    throw new Error(
      typeof detail === "string" ? detail : `HTTP ${response.status}`,
    );
  }
  return response.json() as Promise<T>;
}

export const loadTrace = (runId: string) =>
  get<RunDetail>(`/traces/${encodeURIComponent(runId)}`);

export const listChatTraces = (threadId?: string, limit = 50) =>
  get<RunSummary[]>(
    `/runs?kind=chat&limit=${limit}${threadId ? `&thread_id=${encodeURIComponent(threadId)}` : ""}`,
  );

export function useTrace(runId: string | null) {
  const { data, error, isLoading } = useQuery({
    queryKey: ["runHistory", "trace", runId],
    queryFn: () => loadTrace(runId!),
    enabled: !!runId,
    retry: (count, err) => !(err instanceof TraceNotFound) && count < 2,
  });
  return { run: data, error, isLoading };
}

export function useChatTraces(threadId?: string, limit = 50) {
  const { data, error, isLoading } = useQuery({
    queryKey: ["runHistory", "chatTraces", threadId ?? null, limit],
    queryFn: () => listChatTraces(threadId, limit),
  });
  return { traces: data, error, isLoading };
}
