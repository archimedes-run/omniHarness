"use client";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { SessionRow } from "@/components/workspace/sessions/session-row";
import { useSessions } from "@/core/sessions/hooks";
import { watcherHealth } from "@/core/sessions/logic";

export default function SessionsPage() {
  const { view, isLoading, error } = useSessions();
  const health = view ? watcherHealth(view) : null;

  return (
    <div className="mx-auto w-full max-w-3xl space-y-4 p-6">
      <header className="space-y-1">
        <h1 className="text-xl font-semibold">Coding sessions</h1>
        <p className="text-muted-foreground text-sm">
          What your Claude Code sessions are doing, as the session watcher sees
          them.
        </p>
      </header>

      {isLoading && <p className="text-muted-foreground text-sm">Loading…</p>}

      {error != null && (
        <Alert
          variant="destructive"
          data-testid="watcher-health"
          data-health="error"
        >
          <AlertTitle>I cannot see your sessions</AlertTitle>
          <AlertDescription>{String(error)}</AlertDescription>
        </Alert>
      )}

      {/* FR-013. Watcher health FIRST, and never only implied by the list. */}
      {health?.kind === "cannot-see" && (
        <Alert
          variant="destructive"
          data-testid="watcher-health"
          data-health="cannot-see"
        >
          <AlertTitle>I cannot see your sessions</AlertTitle>
          <AlertDescription>
            {`Sessions may be running — ${health.why}, so nothing here means "none".`}
            {view?.unreachable_detail ? ` (${view.unreachable_detail})` : ""}
          </AlertDescription>
        </Alert>
      )}
      {health?.kind === "stale" && (
        <Alert data-testid="watcher-health" data-health="stale">
          <AlertTitle>{`Last seen ${health.age} ago`}</AlertTitle>
          <AlertDescription>
            The watcher&apos;s data is stale. These are the last-known states,
            not the current ones.
          </AlertDescription>
        </Alert>
      )}
      {health?.kind === "never-observed" && (
        <Alert data-testid="watcher-health" data-health="never-observed">
          <AlertTitle>The watcher has not observed anything yet</AlertTitle>
          <AlertDescription>
            It is running, and has not yet seen a session.
          </AlertDescription>
        </Alert>
      )}
      {health?.kind === "live" && (
        <p
          className="text-muted-foreground text-sm"
          data-testid="watcher-health"
          data-health="live"
        >
          Watcher live.
        </p>
      )}

      {view?.sessions != null && (
        <>
          {/* FR-015: the absence of controls is a property, stated. */}
          <p
            className="text-muted-foreground text-xs"
            data-testid="observe-only"
          >
            {view.observe_only_reason}
          </p>
          {view.sessions.length === 0 ? (
            <p className="text-muted-foreground text-sm" data-testid="empty">
              No sessions seen.
            </p>
          ) : (
            <ul className="space-y-2">
              {view.sessions.map((session) => (
                <SessionRow key={session.session_id} session={session} />
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}
