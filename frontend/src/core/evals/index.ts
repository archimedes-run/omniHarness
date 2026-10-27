import { useQuery } from "@tanstack/react-query";

import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

/** Mirrors the gateway's /api/evals (spec 009 FR-070 to FR-077). */
export interface EvalSummary {
  id: string;
  created_at: string;
  mode: "mock" | "real";
  git_sha: string;
  model: string | null;
  trials: number;
  passed: number;
  total: number;
  strict_passed: number | null;
  cost_usd: number | null;
  seconds: number;
  regressions: string[];
}

export interface EvalCheck {
  name: string;
  pass: boolean;
  reason: string;
}

export interface EvalTask {
  id: string;
  title: string;
  pass: boolean;
  live_only: boolean;
  baseline_pass: boolean | null;
  checks: EvalCheck[];
  seconds: number;
  tokens: { input: number; output: number } | null;
  cost_usd: number | null;
  thread_id: string | null;
}

export interface EvalResult extends EvalSummary {
  tasks: EvalTask[];
}

export interface EvalsIndex {
  baseline: EvalResult | null;
  runs: EvalSummary[];
  results_dir: string;
}

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`${getBackendBaseURL()}/api/evals${path}`);
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

export const loadEvals = () => get<EvalsIndex>("");
export const loadEval = (id: string) =>
  get<EvalResult>(`/${encodeURIComponent(id)}`);

export function useEvals() {
  const { data, error, isLoading } = useQuery({
    queryKey: ["evals"],
    queryFn: loadEvals,
  });
  return { evals: data, error, isLoading };
}

export function useEval(id: string | null) {
  const { data, error, isLoading } = useQuery({
    queryKey: ["evals", id],
    queryFn: () => loadEval(id!),
    enabled: !!id,
  });
  return { result: data, error, isLoading };
}

export function scoreText(s: Pick<EvalSummary, "passed" | "total">): string {
  return `${s.passed}/${s.total}`;
}

export function passRate(s: Pick<EvalSummary, "passed" | "total">): number {
  return s.total > 0 ? s.passed / s.total : 0;
}

/** Oldest first, for the score-history chart. */
export function historyPoints(runs: EvalSummary[], mode: "mock" | "real") {
  return runs
    .filter((r) => r.mode === mode)
    .slice()
    .sort((a, b) => Date.parse(a.created_at) - Date.parse(b.created_at))
    .map((r) => ({
      id: r.id,
      at: r.created_at,
      rate: passRate(r),
      label: scoreText(r),
    }));
}

export type BaselineCell = "pass" | "fail" | "none";

export function baselineCell(task: EvalTask): BaselineCell {
  if (task.baseline_pass === null) return "none";
  return task.baseline_pass ? "pass" : "fail";
}

/** A task that passed in the baseline and fails now. */
export function isRegression(task: EvalTask): boolean {
  return task.baseline_pass === true && !task.pass;
}

/** Failing tasks first, then by id, so what needs attention leads. */
export function sortTasks(tasks: EvalTask[]): EvalTask[] {
  return tasks.slice().sort((a, b) => {
    const ra = isRegression(a) ? 0 : a.pass ? 2 : 1;
    const rb = isRegression(b) ? 0 : b.pass ? 2 : 1;
    return ra - rb || a.id.localeCompare(b.id, undefined, { numeric: true });
  });
}
