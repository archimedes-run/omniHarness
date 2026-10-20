import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

/** Mirrors app/gateway/routers/run_history.py. */
export interface HistorySettings {
  retention_days: number;
  runs: number;
  location: string;
}

export interface RunSummary {
  id: string;
  kind: string;
  source_id: string;
  event_id: string | null;
  thread_id: string | null;
  started_at: string;
  finished_at: string | null;
  status: string;
  error: string | null;
  size: number;
}

export interface RunDetail extends RunSummary {
  body: unknown;
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/run-history${path}`,
    {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    },
  );
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

export const loadSettings = () => call<HistorySettings>("/settings");
export const saveRetention = (retention_days: number) =>
  call<HistorySettings>("/settings", {
    method: "PUT",
    body: JSON.stringify({ retention_days }),
  });
export const deleteAllRuns = () =>
  call<{ deleted: number }>("/runs?confirm=delete-all", { method: "DELETE" });
export const loadRun = (id: string) =>
  call<RunDetail>(`/runs/${encodeURIComponent(id)}`);
