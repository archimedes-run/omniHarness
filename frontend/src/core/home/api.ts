import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type { HomeDismissals, MovedView, UpcomingView } from "./types";

async function read<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${getBackendBaseURL()}/api/home${path}`, init);
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as {
      detail?: unknown;
    };
    throw new Error(
      typeof body.detail === "string"
        ? body.detail
        : `Home could not be read: ${response.status}`,
    );
  }
  return response.json() as Promise<T>;
}

export const loadDismissals = () => read<HomeDismissals>("/dismissals");

export const dismiss = (
  body: { kind: "alert"; keys: string[] } | { kind: "name-prompt" },
) =>
  read<HomeDismissals>("/dismissals", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

export const loadUpcoming = () => read<UpcomingView>("/upcoming");

export const loadMovedToday = (since: string) =>
  read<MovedView>(`/today?since=${encodeURIComponent(since)}`);
