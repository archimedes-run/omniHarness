"""The durable rule-id -> thread-id map (FR-011a/b/c).

Persistence is the requirement, not an optimisation. A map held only in memory
orphans the thread on every restart, which presents as a stable thread in the
specification and behaves as a fresh one in practice — a failure invisible until
someone reads the conversation and finds it has no past.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ._store import JsonStore

logger = logging.getLogger(__name__)

DEFAULT_FIRING_RETENTION = 20


@dataclass
class RuleThreadMap:
    path: Path
    create_thread: Callable[[str], str]
    #: A rule thread's value is remembering the last few firings, not the last
    #: few hundred; beyond that it is context ballast (FR-011c).
    firing_retention: int = DEFAULT_FIRING_RETENTION
    _store: JsonStore | None = None

    def __post_init__(self) -> None:
        self._store = JsonStore(path=self.path)

    def thread_for(self, rule_id: str) -> str:
        """Return this rule's thread, creating it on first firing."""
        existing = self._store.get(rule_id)
        if isinstance(existing, str) and existing:
            return existing
        thread_id = self.create_thread(rule_id)
        self._store.set(rule_id, thread_id)
        logger.info("rule %s: created thread %s", rule_id, thread_id)
        return thread_id

    def forget(self, rule_id: str) -> None:
        """Drop the mapping — used when the recorded thread no longer exists.

        Treated as a first firing rather than a permanent failure.
        """
        self._store.delete(rule_id)

    def known_rules(self) -> list[str]:
        return self._store.keys()
