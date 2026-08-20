"""The live session registry and its own liveness (FR-002, FR-011a, FR-024a).

The load-bearing idea here is small and easy to lose: an EMPTY registry and an
UNOBSERVABLE one are different facts. A silently dead watcher returns an empty
registry, and an empty registry renders as "you have no sessions running" through
an entirely normal code path — a false negative that reads as fact and sends the
user away from a machine that is still working.

So observability is not derived at the call site. It is a field.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

from .models import Session

DEFAULT_HEARTBEAT_INTERVAL_S = 30
#: Tolerates two missed heartbeats before declaring staleness.
DEFAULT_STALENESS_THRESHOLD_S = 90


class Observability(StrEnum):
    """The three conditions that must never collapse into two (FR-011a)."""

    LIVE = "live"  # fresh heartbeat; contents are current
    STALE = "stale"  # heartbeat aged out; contents are last-known
    NEVER_OBSERVED = "never-observed"  # no heartbeat ever; we have never seen anything


@dataclass
class RegistryConfig:
    heartbeat_interval_s: int = DEFAULT_HEARTBEAT_INTERVAL_S
    staleness_threshold_s: int = DEFAULT_STALENESS_THRESHOLD_S


@dataclass
class SessionRegistry:
    config: RegistryConfig = field(default_factory=RegistryConfig)
    sessions: dict[str, Session] = field(default_factory=dict)
    last_heartbeat_at: datetime | None = None

    # ---- liveness -------------------------------------------------------

    def heartbeat(self, now: datetime) -> None:
        self.last_heartbeat_at = now

    def observability(self, now: datetime) -> Observability:
        if self.last_heartbeat_at is None:
            return Observability.NEVER_OBSERVED
        age = now - self.last_heartbeat_at
        if age > timedelta(seconds=self.config.staleness_threshold_s):
            return Observability.STALE
        return Observability.LIVE

    def is_observable(self, now: datetime) -> bool:
        return self.observability(now) is Observability.LIVE

    def staleness_seconds(self, now: datetime) -> int:
        if self.last_heartbeat_at is None:
            return -1  # sentinel: not "0 seconds stale", but "never seen"
        return max(0, int((now - self.last_heartbeat_at).total_seconds()))

    # ---- contents -------------------------------------------------------

    def replace_all(self, sessions: list[Session], now: datetime) -> None:
        """Install a fresh sweep's results and beat. Both, together, always.

        Updating contents without beating would leave fresh data looking stale;
        beating without updating would leave stale data looking fresh. Neither is
        a state we want representable, so there is one method.
        """
        self.sessions = {s.session_id: s for s in sessions}
        self.heartbeat(now)

    def upsert(self, session: Session) -> None:
        self.sessions[session.session_id] = session

    def get(self, key: str) -> Session | None:
        """Look up by session id, falling back to an exact project-name match."""
        if key in self.sessions:
            return self.sessions[key]
        matches = self.match_project(key)
        return matches[0] if len(matches) == 1 else None

    def match_project(self, key: str) -> list[Session]:
        """All sessions whose project matches. More than one means ask (FR-017)."""
        k = key.lower()
        exact = [s for s in self.sessions.values() if s.project.lower() == k]
        if exact:
            return exact
        # Tolerate "darcy-repo" matching "darcy-repo@main".
        return [s for s in self.sessions.values() if s.project.lower().split("@")[0] == k]

    def all_sessions(self) -> list[Session]:
        return sorted(self.sessions.values(), key=lambda s: s.last_activity_at, reverse=True)

    @property
    def is_empty(self) -> bool:
        return not self.sessions
