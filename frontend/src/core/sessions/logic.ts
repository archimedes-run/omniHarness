import type { DisplayState, SessionsView } from "./types";

export type WatcherHealth =
  | { kind: "live" }
  | { kind: "stale"; age: string }
  | { kind: "never-observed" }
  | { kind: "cannot-see"; why: string };

function age(seconds: number | null): string {
  if (seconds == null) return "an unknown time";
  if (seconds < 90) return `${seconds}s`;
  if (seconds < 90 * 60) return `${Math.round(seconds / 60)} min`;
  return `${Math.round(seconds / 3600)} h`;
}

/**
 * Watcher health, first (FR-013). Four answers, because an empty list could
 * mean any of them and only one of them means "nothing is running".
 */
export function watcherHealth(view: SessionsView): WatcherHealth {
  if (!view.reachable) {
    const why =
      view.unreachable_kind === "not-configured"
        ? "the session watcher has never been configured"
        : view.unreachable_kind === "disabled"
          ? "the session watcher is disabled"
          : "the session watcher is not answering";
    return { kind: "cannot-see", why };
  }
  if (view.observability === "stale")
    return { kind: "stale", age: age(view.staleness_seconds) };
  if (view.observability === "never-observed")
    return { kind: "never-observed" };
  return { kind: "live" };
}

/** Completed and stalled kept apart (FR-012); waiting hedged (FR-011). */
export const STATE_LABEL: Record<DisplayState, string> = {
  working: "Working",
  "waiting-on-user": "Looks like it's waiting on you",
  completed: "Finished",
  stalled: "May have stalled",
  failed: "Failed",
  unknown: "Cannot tell",
};
