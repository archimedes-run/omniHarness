"""Session-watcher triggers (FR-002, FR-028, FR-029).

The watcher may be on another host, reached over a private network — Feature 001
runs on the user's laptop while this engine is expected to run on an always-on
box. Nothing here may assume co-location.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from ..models import Rule, TriggerEvent, TriggerType
from .base import SourceUnavailable, TriggerSource

logger = logging.getLogger(__name__)


@dataclass
class WatcherSource(TriggerSource):
    """`fetch_sessions` returns the watcher's roll-up payload, or raises."""

    fetch_sessions: Callable[[], dict]
    last_error: str | None = None
    reachable: bool = True

    def poll(self, rule: Rule, now: datetime) -> list[TriggerEvent]:
        wanted = rule.match.get("event")
        try:
            payload = self.fetch_sessions()
        except Exception as exc:  # noqa: BLE001
            self.reachable, self.last_error = False, f"{type(exc).__name__}: {exc}"
            # NOT an empty list. Returning [] here would be indistinguishable
            # from "we looked and nothing is happening", which is precisely the
            # claim FR-029 forbids making when we could not look at all.
            raise SourceUnavailable(self.last_error) from exc

        if not payload.get("observable", False):
            self.reachable = False
            self.last_error = f"watcher reports observability={payload.get('observability')}"
            raise SourceUnavailable(self.last_error)

        self.reachable, self.last_error = True, None
        out: list[TriggerEvent] = []
        for s in payload.get("sessions", []):
            if not _matches(s, wanted):
                continue
            out.append(
                TriggerEvent(
                    type=TriggerType.WATCHER,
                    event_id=str(s.get("session_id", "")),
                    at=now,
                    fields={
                        "project": s.get("project", ""),
                        "session_id": s.get("session_id", ""),
                        "last_message": s.get("summary", ""),
                        "state": s.get("state", ""),
                        "idle_reason": s.get("idle_reason") or "",
                    },
                    # Only non-drifting values (FR-017b). `summary` stands in for
                    # the pending question; quiet_seconds and elapsed_seconds are
                    # deliberately absent — including either would make every
                    # evaluation a "new" event and produce an alert per cycle.
                    fingerprint_inputs={
                        "question": s.get("summary", ""),
                        "state": s.get("state", ""),
                        "idle_reason": s.get("idle_reason") or "",
                    },
                )
            )
        return out

    def describe(self) -> dict:
        """Runtime-inspectable reachability (FR-029)."""
        return {"reachable": self.reachable, "last_error": self.last_error, "checked_at": datetime.now(UTC).isoformat()}


def _matches(session: dict, wanted: str | None) -> bool:
    if not wanted:
        return False
    if wanted == "waiting-on-user":
        return session.get("state") == "waiting-on-user"
    if wanted == "session-failed":
        return session.get("state") == "failed"
    return session.get("state") == wanted
