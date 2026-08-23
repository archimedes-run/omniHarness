"""Durable serialisation for pending firings.

WHY THIS EXISTS. Quiet-hours deferrals and an open coalescing window lived only
in the runner's memory. Under single-runner election that memory belongs to one
worker, and when that worker dies its contents are not delayed — they are lost.

The loss is silent and permanent, because the fingerprint that suppresses
re-firing is written BEFORE delivery. A firing dying in a dead worker's window
is therefore both undelivered and already marked seen, so no successor
re-derives it. For a morning briefing that is one missed message; for a blocked
session it is the one notification the feature exists to send.

Uses the same JsonStore as the fingerprint store, so pending firings share the
durability and atomic-write behaviour of the state they are already keyed
against, rather than introducing a second persistence mechanism to reason about.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ._store import JsonStore
from .models import Firing, Outcome, TriggerEvent, TriggerType

logger = logging.getLogger(__name__)


def to_dict(firing: Firing) -> dict:
    return {
        "rule_id": firing.rule_id,
        "prompt": firing.prompt,
        "thread_id": firing.thread_id,
        "reply": firing.reply,
        "outcome": str(firing.outcome) if firing.outcome else None,
        "reason": firing.reason,
        "event": {
            "type": str(firing.event.type),
            "event_id": firing.event.event_id,
            "at": firing.event.at.isoformat(),
            "fields": firing.event.fields,
            "fingerprint_inputs": firing.event.fingerprint_inputs,
        },
    }


def from_dict(raw: dict) -> Firing:
    ev = raw["event"]
    firing = Firing(
        rule_id=raw["rule_id"],
        event=TriggerEvent(
            type=TriggerType(ev["type"]),
            event_id=ev["event_id"],
            at=datetime.fromisoformat(ev["at"]),
            fields=ev.get("fields") or {},
            fingerprint_inputs=ev.get("fingerprint_inputs") or {},
        ),
        prompt=raw["prompt"],
        thread_id=raw.get("thread_id"),
        reply=raw.get("reply"),
        reason=raw.get("reason") or "",
    )
    if raw.get("outcome"):
        firing.outcome = Outcome(raw["outcome"])
    return firing


@dataclass
class PendingStore:
    """Durable list of firings awaiting release, keyed by queue name.

    A successor reads these back and puts them through the SAME release path
    the original worker would have used — re-check, coalesce, redact, deliver.
    That matters: releasing them directly would deliver a burst of firings whose
    conditions may no longer hold, which is the failure quiet hours and
    coalescing exist to prevent.
    """

    path: Path
    _store: JsonStore | None = None

    def __post_init__(self) -> None:
        self._store = JsonStore(path=self.path)

    def save(self, queue: str, firings: list[Firing]) -> None:
        self._store.set(queue, [to_dict(f) for f in firings])

    def load(self, queue: str) -> list[Firing]:
        raw = self._store.get(queue) or []
        out: list[Firing] = []
        for item in raw:
            try:
                out.append(from_dict(item))
            except (KeyError, ValueError, TypeError) as exc:
                # One unreadable entry must not strand the rest. Report it —
                # a silently dropped firing is the defect this file exists for.
                logger.error("dropping unreadable pending firing in %r: %s", queue, exc)
        return out
