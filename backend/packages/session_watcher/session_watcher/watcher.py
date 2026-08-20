"""Filesystem watching plus reconciliation (FR-022, FR-024, SC-006).

watchdog is the FAST path, not the source of truth. FSEvents coalesces and can
drop events under load, and sleep/wake produces exactly the gap that would
otherwise strand the registry on stale data forever. So a low-frequency
reconciliation sweep re-establishes truth on its own schedule: a missed event
delays an update, it never loses one.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

DEFAULT_RECONCILE_S = 30
DEFAULT_DEBOUNCE_S = 0.5


@dataclass
class WatchConfig:
    reconcile_interval_s: int = DEFAULT_RECONCILE_S
    debounce_s: float = DEFAULT_DEBOUNCE_S
    #: Set when the OS or filesystem cannot support change notification.
    force_polling: bool = False


@dataclass
class Reconciler:
    """Decides when a sweep is due. Pure logic, so it is testable without a clock.

    Kept separate from the watchdog wiring on purpose: the interesting behaviour
    (sleep/wake, missed events, debounce) is all here and needs no filesystem.
    """

    config: WatchConfig = field(default_factory=WatchConfig)
    last_sweep_at: datetime | None = None
    _dirty: bool = False

    def note_change(self) -> None:
        """A filesystem event arrived. Cheap; the sweep is what costs."""
        self._dirty = True

    def due(self, now: datetime) -> bool:
        if self.last_sweep_at is None:
            return True
        elapsed = now - self.last_sweep_at
        if self._dirty and elapsed >= timedelta(seconds=self.config.debounce_s):
            return True
        # The unconditional heartbeat sweep. This is what survives a dropped
        # event or a laptop that slept through several: no event ever arrives,
        # yet truth is re-established anyway.
        return elapsed >= timedelta(seconds=self.config.reconcile_interval_s)

    def note_swept(self, now: datetime) -> None:
        self.last_sweep_at = now
        self._dirty = False

    def detect_gap(self, now: datetime) -> timedelta | None:
        """A gap far larger than the interval means we were asleep (FR-024)."""
        if self.last_sweep_at is None:
            return None
        elapsed = now - self.last_sweep_at
        if elapsed > timedelta(seconds=self.config.reconcile_interval_s * 4):
            return elapsed
        return None


class FileWatcher:
    """Wires watchdog to a callback, falling back to polling where needed."""

    def __init__(self, root, on_change: Callable[[], None], config: WatchConfig | None = None):
        self.root = root
        self.on_change = on_change
        self.config = config or WatchConfig()
        self._observer = None
        self._stop = threading.Event()

    def start(self) -> str:
        """Returns the mode actually in use: 'native' or 'polling'."""
        if self.config.force_polling:
            return self._start_polling()
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer

            handler = FileSystemEventHandler()
            handler.on_any_event = lambda _e: self.on_change()
            self._observer = Observer()
            self._observer.schedule(handler, str(self.root), recursive=True)
            self._observer.start()
            return "native"
        except Exception as exc:  # noqa: BLE001 - degrade rather than fail to start
            logger.info("native watching unavailable (%s); falling back to polling", exc)
            return self._start_polling()

    def _start_polling(self) -> str:
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers.polling import PollingObserver

        handler = FileSystemEventHandler()
        handler.on_any_event = lambda _e: self.on_change()
        self._observer = PollingObserver(timeout=self.config.reconcile_interval_s)
        self._observer.schedule(handler, str(self.root), recursive=True)
        self._observer.start()
        return "polling"

    def stop(self) -> None:
        self._stop.set()
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=5)
