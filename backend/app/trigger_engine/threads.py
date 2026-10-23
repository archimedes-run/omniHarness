"""The durable rule-id -> thread-id map (FR-011a/b/c).

Persistence is the requirement, not an optimisation. A map held only in memory
orphans the thread on every restart, which presents as a stable thread in the
specification and behaves as a fresh one in practice — a failure invisible until
someone reads the conversation and finds it has no past.
"""

from __future__ import annotations

import fcntl
import logging
import time
from collections.abc import Callable
from contextlib import contextmanager
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
    #: Told of every thread this map creates (the run history's ledger of
    #: automation threads), BEFORE the map points at it. Optional.
    on_created: Callable[[str, str], None] | None = None
    _store: JsonStore | None = None

    def __post_init__(self) -> None:
        # The file is authoritative (cache=False): the engine re-reads the map
        # before each firing, so a thread another worker deleted (and forgot)
        # is never reused from a stale in-memory copy.
        self._store = JsonStore(path=self.path, cache=False)

    @contextmanager
    def firing_lock(self, *, timeout: float | None = None):
        """Exclusive, across processes, on this map's threads. The engine holds
        it for each firing (resolve the thread, run the turn); deleting the
        automations' threads holds it for the whole delete. Yields True when
        held; with `timeout`, yields False if it could not be had in time."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path.parent / "threads.firing.lock", "a") as fh:
            deadline = None if timeout is None else time.monotonic() + timeout
            while True:
                try:
                    fcntl.flock(fh, fcntl.LOCK_EX | (fcntl.LOCK_NB if deadline is not None else 0))
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        yield False
                        return
                    time.sleep(0.05)
            try:
                yield True
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)

    def thread_for(self, rule_id: str) -> str:
        """Return this rule's thread, creating it on first firing."""
        existing = self._store.get(rule_id)
        if isinstance(existing, str) and existing:
            return existing
        thread_id = self.create_thread(rule_id)
        if self.on_created is not None:
            self.on_created(rule_id, thread_id)
        self._store.set(rule_id, thread_id)
        logger.info("rule %s: created thread %s", rule_id, thread_id)
        return thread_id

    def forget(self, rule_id: str) -> None:
        """Drop the mapping — used when the recorded thread no longer exists.

        Treated as a first firing rather than a permanent failure.
        """
        self._store.delete(rule_id)

    def thread_of(self, rule_id: str) -> str | None:
        """This rule's recorded thread, without creating one."""
        existing = self._store.get(rule_id)
        return existing if isinstance(existing, str) and existing else None

    def known_rules(self) -> list[str]:
        return self._store.keys()
