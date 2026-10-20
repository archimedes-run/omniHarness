import { useSessions } from "@/core/sessions/hooks";
import { watcherHealth, type WatcherHealth } from "@/core/sessions/logic";
import type { SessionRow, SessionsView } from "@/core/sessions/types";

export interface SessionsState {
  view: SessionsView | undefined;
  health: WatcherHealth | null;
  isLoading: boolean;
  /** Why the sessions cannot be seen, or null when they can. */
  cantTell: string | null;
  /** Sessions that look blocked on the user; undefined while unknown. */
  waiting: SessionRow[] | undefined;
  live: boolean;
}

/** The session watcher, as the sessions page reads it (one query, shared by
 * Waiting on you and the Coding sessions card). */
export function useHomeSessions(): SessionsState {
  const { view, isLoading, error } = useSessions();
  const health = view ? watcherHealth(view) : null;
  const cantTell =
    error != null
      ? `the gateway did not answer (${String(error)})`
      : health?.kind === "cannot-see"
        ? health.why
        : view && view.sessions == null
          ? "the watcher sent no sessions"
          : null;
  const waiting =
    cantTell == null && view?.sessions
      ? view.sessions.filter((s) => s.display_state === "waiting-on-user")
      : undefined;
  return {
    view,
    health,
    isLoading,
    cantTell,
    waiting,
    live: health?.kind === "live",
  };
}
