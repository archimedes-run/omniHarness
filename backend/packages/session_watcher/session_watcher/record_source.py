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
import time
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path

logger = logging.getLogger(__name__)

#: An unknown record type is logged at INFO the first time it is seen, then at
#: most once per this interval with the count since. It was once logged per
#: record, on every re-read of every file: 27,000 lines a minute.
UNKNOWN_TYPE_LOG_INTERVAL_S = 600.0


class SkipReason(StrEnum):
    """Why an entry produced no ParsedRecord.

    Split apart because lumping them together hides real drift in a flood of
    normal bookkeeping: on a real corpus, ~5.4k entries lack a timestamp simply
    because that is the shape of `mode`/`ai-title`/`last-prompt` records. If
    those log as damage, an actual format change is invisible in the noise.
    """

    MALFORMED = "malformed-json"  # genuine damage: truncation, corruption
    NO_TIMESTAMP = "no-timestamp"  # normal for bookkeeping record types
    NO_SESSION_ID = "no-session-id"  # normal for a few header-ish records
    INERT_TYPE = "known-inert-type"  # recognised, carries no status meaning
    UNKNOWN_TYPE = "unknown-type"  # NOVEL: the one that means the format moved


@dataclass
class RecordStats:
    records_opened: int = 0
    #: Bytes actually read. An append must cost the appended bytes, not the file
    #: (Gate 3, extended): re-reading an 85 MB transcript on every append held a
    #: core at 100% and timed the gateway out.
    bytes_read: int = 0
    records_skipped: int = 0
    candidates_considered: int = 0
    skips: Counter[str] = field(default_factory=Counter)
    #: Record types never seen before, whether the record was skipped (no
    #: timestamp) or parsed (it had one). Both mean the format moved.
    unknown_types: Counter[str] = field(default_factory=Counter)
    #: Named shape changes inside a KNOWN type ("session_meta:subagent-without-
    #: parent"): format drift too, but not a record type, so kept apart.
    diagnostics: Counter[str] = field(default_factory=Counter)
    #: Records with no type at all.
    untyped: int = 0

    @property
    def drift_signals(self) -> int:
        """Everything that suggests the format changed under us, counted once:
        damaged lines, records with no type, unknown types (skipped or parsed)
        and named shape changes. The same rule for every adapter."""
        return self.skips[SkipReason.MALFORMED] + self.untyped + sum(self.unknown_types.values()) + sum(self.diagnostics.values())

    def reset(self) -> None:
        self.records_opened = 0
        self.bytes_read = 0
        self.records_skipped = 0
        self.candidates_considered = 0
        self.skips.clear()
        self.unknown_types.clear()
        self.diagnostics.clear()
        self.untyped = 0


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
    _unknown_logged_at: dict[str, float] = field(default_factory=dict)
    _unknown_since_log: Counter[str] = field(default_factory=Counter)

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

    def read_from(self, path: Path, offset: int) -> bytes:
        """Read a record file from `offset` to its current end. Counts as an open.

        Binary, so offsets are byte positions a later call can resume from; the
        caller decodes whole lines only, leaving a partial last line unread until
        its newline arrives.
        """
        self.stats.records_opened += 1
        with path.open("rb") as fh:
            fh.seek(offset)
            data = fh.read()
        self.stats.bytes_read += len(data)
        return data

    def note_skip(
        self,
        reason: SkipReason,
        path: Path,
        lineno: int,
        *,
        raw_type: str | None = None,
    ) -> None:
        """Record a skipped entry at debug level and keep going (FR-009)."""
        self.stats.records_skipped += 1
        self.stats.skips[reason] += 1
        if reason is SkipReason.UNKNOWN_TYPE and raw_type:
            self.note_unknown(raw_type, path, lineno)
        elif reason is SkipReason.UNKNOWN_TYPE:
            self.stats.untyped += 1
            logger.debug("record with no type at %s:%d", path, lineno)
        else:
            logger.debug("skipping %s:%d — %s", path, lineno, reason)

    def note_unknown(self, raw_type: str, path: Path, lineno: int) -> None:
        """A record type never seen before: drift, whether or not it parsed."""
        self.stats.unknown_types[raw_type] += 1
        self._log_drift("unknown record type", raw_type, path, lineno)

    def note_diagnostic(self, key: str, path: Path, lineno: int) -> None:
        """A named shape change inside a known type: drift, kept apart."""
        self.stats.diagnostics[key] += 1
        self._log_drift("unexpected record shape", key, path, lineno)

    def _log_drift(self, what: str, key: str, path: Path, lineno: int) -> None:
        # Louder than debug: drift is the signal that the observed format
        # moved. Everything else here is routine. Rate limited per key, so
        # the signal stays readable.
        self._unknown_since_log[key] += 1
        now = time.monotonic()
        last = self._unknown_logged_at.get(key)
        if last is None or now - last >= UNKNOWN_TYPE_LOG_INTERVAL_S:
            count = self._unknown_since_log.pop(key)
            self._unknown_logged_at[key] = now
            logger.info("%s %r at %s:%d (%d occurrence(s) since last report)", what, key, path, lineno, count)
        else:
            logger.debug("%s %r at %s:%d", what, key, path, lineno)
