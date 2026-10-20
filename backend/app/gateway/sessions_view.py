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


class TodoItem(BaseModel):
    title: str
    #: pending | in_progress | completed
    status: str


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
    #: The summary failed redaction and is not shown (FR-031, SC-015).
    withheld: bool = False
    #: Which coding agent (Feature 005 FR-020): "claude" or "codex".
    agent: str = "claude"
    agent_label: str = "Claude Code"
    #: The agent's own todo list as of its last CONFIRMED update (FR-031);
    #: None when it has never made one. Titles redacted, or Withheld.
    todos: list[TodoItem] | None = None
    #: How many files its successful tool results changed.
    files_changed: int = 0


class AgentHealth(BaseModel):
    """Per-agent: can its files be read, and how much format drift was seen."""

    agent: str
    label: str
    readable: bool
    reason: str | None = None
    drift: int = 0


class SessionsView(BaseModel):
    reachable: bool
    #: Why not, when not: not-configured | disabled | unreachable.
    unreachable_kind: str | None = None
    unreachable_detail: str | None = None
    observability: str | None = None
    staleness_seconds: int | None = None
    as_of: str | None = None
    #: None when the watcher could not be asked and there is no earlier answer.
    #: Never [] for that.
    sessions: list[SessionRow] | None = None
    #: Set when the watcher did not answer in time and `sessions` is its LAST
    #: answer, this many seconds old. `reachable` is False alongside it.
    last_known_age_seconds: int | None = None
    #: One per configured agent. An unreadable one is "can't tell" for that
    #: agent, never "no sessions" (Feature 005 FR-026).
    agents: list[AgentHealth] = []
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


def _agent(a: dict) -> AgentHealth:
    return AgentHealth(
        agent=str(a.get("agent")),
        label=str(a.get("label") or a.get("agent")),
        readable=bool(a.get("readable")),
        reason=a.get("reason"),
        drift=int(a.get("drift") or 0),
    )


def describe_sessions(payload: dict | None, failure: Exception | None = None) -> SessionsView:
    """Pure. `payload` is the watcher's roll-up, or None with `failure` saying why not.

    The watcher redacts its summaries before it sends them. They are redacted
    again here, because this surface's guarantee cannot rest on another
    process's (FR-031)."""
    from app.gateway.display_redaction import for_display

    if payload is None:
        from app.gateway.watcher_client import WatcherDisabled, WatcherNotConfigured

        kind = "not-configured" if isinstance(failure, WatcherNotConfigured) else "disabled" if isinstance(failure, WatcherDisabled) else "unreachable"
        return SessionsView(reachable=False, unreachable_kind=kind, unreachable_detail=str(failure) if failure else None)

    rows = []
    for s in payload.get("sessions", []):
        display, epistemic = _display(s)
        summary, summary_withheld = for_display(s.get("summary") or "")
        project, project_withheld = for_display(str(s.get("project", "")))
        todos = None
        if isinstance(s.get("todos"), list):
            # Agent-written titles: redacted again here (FR-019, FR-031 of 004).
            todos = [TodoItem(title=for_display(str(t.get("title", "")))[0], status=str(t.get("status", "pending"))) for t in s["todos"] if isinstance(t, dict)]
        rows.append(
            SessionRow(
                session_id=str(s.get("session_id", "")),
                project=project,
                display_state=display,
                epistemic=epistemic,
                last_activity_at=s.get("last_activity_at"),
                quiet_seconds=s.get("quiet_seconds"),
                summary=summary,
                summary_provenance=s.get("summary_provenance") or "",
                relay_suppressed=bool(s.get("relay_suppressed")),
                withheld=summary_withheld or project_withheld,
                agent=str(s.get("agent") or "claude"),
                agent_label=str(s.get("agent_label") or "Claude Code"),
                todos=todos,
                files_changed=len(s.get("files_changed") or []),
            )
        )
    return SessionsView(
        reachable=True,
        observability=payload.get("observability"),
        staleness_seconds=payload.get("staleness_seconds"),
        as_of=payload.get("as_of"),
        sessions=rows,
        agents=[
            AgentHealth(agent=str(a.get("agent")), label=str(a.get("label") or a.get("agent")), readable=bool(a.get("readable")), reason=a.get("reason"), drift=int(a.get("drift") or 0))
            for a in payload.get("agents") or []
            if isinstance(a, dict)
        ],
    )
