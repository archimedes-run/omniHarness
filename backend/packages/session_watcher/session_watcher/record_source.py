"""The single seam through which every session record is opened (Gate 3).

Why this exists as a class rather than a bare helper: the startup bound in
SC-004i is asserted on the *count of records opened*, and a counter with a second
path around it measures nothing. Direct open()/Path.read_text inside the adapter
is banned by ruff so this cannot be bypassed by accident.

A wall-clock bound was the alternative and is strictly worse — it passes on fast
hardware even when a full directory scan has been reintroduced.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class RecordStats:
    records_opened: int = 0
    records_skipped: int = 0
    candidates_considered: int = 0

    def reset(self) -> None:
        self.records_opened = 0
        self.records_skipped = 0
        self.candidates_considered = 0


@dataclass
class RecordSource:
    """Opens session records and counts every open.

    `root` is the session-history directory. Paths are handled exclusively with
    pathlib — observed project directories are slugs beginning with "-", which a
    shell reads as an option flag (research R2 finding 2). The module-wide
    subprocess ban makes that unrepresentable rather than merely discouraged.
    """

    root: Path
    stats: RecordStats = field(default_factory=RecordStats)

    def select_candidates(self, window: timedelta, *, now: datetime | None = None) -> list[Path]:
        """Filter by modification time BEFORE opening anything (FR-005d).

        This is what makes the startup cost scale with the window instead of the
        directory. Bypassing it is the exact regression Gate 3 watches for.
        """
        if not self.root.exists():
            return []
        now = now or datetime.now().astimezone()
        cutoff = (now - window).timestamp()
        out: list[Path] = []
        for path in self.root.rglob("*.jsonl"):
            self.stats.candidates_considered += 1
            try:
                if path.stat().st_mtime >= cutoff:
                    out.append(path)
            except OSError as exc:  # unreadable/vanished between listing and stat
                logger.debug("skipping unstattable candidate %s: %s", path, exc)
        return sorted(out)

    @contextmanager
    def open(self, path: Path) -> Iterator[Iterator[str]]:
        """The ONLY permitted way to open a record. Increments records_opened."""
        self.stats.records_opened += 1
        fh = path.open("r", encoding="utf-8", errors="replace")
        try:
            yield fh
        finally:
            fh.close()

    def note_skip(self, reason: str, path: Path, lineno: int) -> None:
        """Record an unparseable entry at debug level and keep going (FR-009)."""
        self.stats.records_skipped += 1
        logger.debug("skipping %s:%d — %s", path, lineno, reason)
