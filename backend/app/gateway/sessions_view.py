"""What the coding-session surface shows (Feature 004, US3).

Two facts, never one (T062). `reachable` is TRANSPORT: could the gateway ask
the watcher at all. `observability` is the WATCHER's own report on its data:
live, stale (with its age), or never-observed. Collapsing them would undo
Feature 001's FR-011a, which exists to keep three conditions from becoming two —
and an unreachable watcher would render as an empty list, which reads as "no
sessions are running", a false negative stated as fact (SC-006).

So when the watcher cannot be reached, `sessions` is None, not [].
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

#: How a state is known (FR-011, FR-012). Waiting-on-user is inferred from a
#: turn that ended on a question; stalled from inactivity. Completed was seen
#: (an end-of-turn record); so were working and failed.
Epistemic = Literal["observed", "inferred", "unknown"]

OBSERVE_ONLY_REASON = "Sessions are observed, never controlled: the watcher reads session logs and cannot approve, stop or reply to a session (Feature 001 FR-015, Article IV)."


class SessionRow(BaseModel):
    session_id: str
    project: str
    #: One of working, waiting-on-user, completed, stalled, failed, unknown —
    #: completed and stalled kept apart (FR-012).
    display_state: str
    epistemic: Epistemic
    last_activity_at: str | None = None
    quiet_seconds: int | None = None
    summary: str = ""
    summary_provenance: str = ""
    relay_suppressed: bool = False


class SessionsView(BaseModel):
    reachable: bool
    #: Why not, when not: not-configured | disabled | unreachable.
    unreachable_kind: str | None = None
    unreachable_detail: str | None = None
    observability: str | None = None
    staleness_seconds: int | None = None
    as_of: str | None = None
    #: None when the watcher could not be asked. Never [] for that.
    sessions: list[SessionRow] | None = None
    observe_only: bool = True
    observe_only_reason: str = OBSERVE_ONLY_REASON


def _display(row: dict) -> tuple[str, Epistemic]:
    state, idle = row.get("state"), row.get("idle_reason")
    if state == "idle":
        return ("completed", "observed") if idle == "completed" else ("stalled", "inferred")
    if state == "waiting-on-user":
        return "waiting-on-user", "inferred"
    if state in ("working", "failed"):
        return state, "observed"
    return "unknown", "unknown"


def describe_sessions(payload: dict | None, failure: Exception | None = None) -> SessionsView:
    """Pure. `payload` is the watcher's roll-up, or None with `failure` saying why not."""
    if payload is None:
        from app.gateway.watcher_client import WatcherDisabled, WatcherNotConfigured

        kind = "not-configured" if isinstance(failure, WatcherNotConfigured) else "disabled" if isinstance(failure, WatcherDisabled) else "unreachable"
        return SessionsView(reachable=False, unreachable_kind=kind, unreachable_detail=str(failure) if failure else None)

    rows = []
    for s in payload.get("sessions", []):
        display, epistemic = _display(s)
        rows.append(
            SessionRow(
                session_id=str(s.get("session_id", "")),
                project=str(s.get("project", "")),
                display_state=display,
                epistemic=epistemic,
                last_activity_at=s.get("last_activity_at"),
                quiet_seconds=s.get("quiet_seconds"),
                summary=s.get("summary") or "",
                summary_provenance=s.get("summary_provenance") or "",
                relay_suppressed=bool(s.get("relay_suppressed")),
            )
        )
    return SessionsView(
        reachable=True,
        observability=payload.get("observability"),
        staleness_seconds=payload.get("staleness_seconds"),
        as_of=payload.get("as_of"),
        sessions=rows,
    )
