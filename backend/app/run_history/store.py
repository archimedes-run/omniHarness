"""A durable, local store of runs: inputs, tool calls and results, outputs.

GATED: a run can carry mail and calendar content, so these are the guarantees,
each tested (tests/run_history):

  * FULL CONTENT, WITHIN CAPS. Not cut at 10 KB as the run_events table cuts
    trace content. A body above INLINE_MAX bytes is written to its own file
    under `blobs/`, atomically, and the row names it. One run is capped at
    RUN_MAX_BYTES: past it the longest strings are cut, each cut says so, and
    the body carries `cut`. The whole history is capped at TOTAL_MAX_BYTES:
    past it a run is recorded without its content, and `warning()` (shown in
    Settings) says so; it warns from WARN_FRACTION of the cap.
  * SECRETS REDACTED BEFORE STORING. Every string in the run, at any depth, is
    first cleared of every secret VALUE the process loaded (exact match, also
    base64 and URL-encoded; see default_redactor), then goes
    through the same credential patterns the session watcher and the trigger
    engine's deliveries use (session_watcher.redaction), plus the URL
    credential filter the gateway's logs use. A string redaction cannot be
    completed for is stored as WITHHELD, never as it was: the store fails
    closed. Nothing unredacted reaches the database or a blob file.
  * RETENTION. Runs older than the retention (30 days by default, changeable)
    are purged, rows and blob files both, by `purge()`, with SQLite's
    secure_delete on, so a purged row's bytes are zeroed in the file rather
    than left in a free page; the gateway runs it at
    startup and every hour (lifespan.py).
  * LOCAL ONLY. A SQLite file and a directory under the gateway's data dir,
    the directory 0700 and the database 0600. Nothing here syncs anywhere.
  * DELETABLE. `delete_all()` removes every run and every blob file.

Thread-safe: one connection per call, and SQLite's own locking. One lock
covers a record's blob AND row, and a delete's rows AND blobs, so neither can
land between the other's two steps; a blob that is missing anyway (another
process) reads as BLOB_MISSING, never an error. The trigger
engine records from its worker thread; the routers read from the event loop.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import tempfile
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Bodies larger than this (bytes of JSON) go to a blob file, not the row.
INLINE_MAX = 64 * 1024
DEFAULT_RETENTION_DAYS = 30
#: What a string is stored as when it could not be redacted.
WITHHELD = "[Withheld: could not be redacted]"
#: A run's body when its blob file is missing or unreadable.
BLOB_MISSING = "[Withheld: this run's stored content is missing or unreadable]"
#: One run's stored body is cut to this (bytes of JSON): the longest strings
#: are shortened first, each saying how much was cut, and the body says so.
RUN_MAX_BYTES = 2 * 1024 * 1024
#: The whole history's cap. Past it a run is recorded WITHOUT its content, and
#: the settings say so; at WARN_FRACTION of it the settings warn.
TOTAL_MAX_BYTES = 512 * 1024 * 1024
WARN_FRACTION = 0.9

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    source_id TEXT NOT NULL,
    event_id TEXT,
    thread_id TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    error TEXT,
    size INTEGER NOT NULL,
    body TEXT,
    blob TEXT
);
CREATE INDEX IF NOT EXISTS runs_source ON runs (kind, source_id, started_at);
CREATE INDEX IF NOT EXISTS runs_started ON runs (started_at);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def default_redactor(known=None) -> Callable[[str], tuple[str, bool]]:
    """The run history's redaction, as (text, ok). Two passes, in this order:

    1. EXACT MATCH: every secret value this process loaded (.env, config.yaml,
       the extensions config, the MCP vault, the OAuth stores, and each token
       as it is refreshed), in raw, base64 and URL-encoded forms
       (omniharness.utils.known_secrets). This catches values no pattern
       recognises.
    2. PATTERNS: the credential shapes the session watcher and the trigger
       engine's deliveries use, plus the URL credential filter of the logs.

    Either pass failing withholds the string.
    """
    from session_watcher.redaction import Channel, redact_or_suppress

    from app.gateway.log_redaction import redact_url_credentials
    from omniharness.utils.known_secrets import KNOWN_SECRETS

    registry = KNOWN_SECRETS if known is None else known

    def _redact(text: str) -> tuple[str, bool]:
        try:
            text, _ = registry.redact(text)
        except Exception:  # noqa: BLE001 — fail closed
            return WITHHELD, False
        out, ok = redact_or_suppress(text, Channel.LOCAL)
        if not ok:
            return WITHHELD, False
        return redact_url_credentials(out), True

    return _redact


def redact_tree(value: Any, redact: Callable[[str], tuple[str, bool]]) -> Any:
    """Every string in `value`, at any depth (keys included), redacted."""
    if isinstance(value, str):
        return redact(value)[0]
    if isinstance(value, dict):
        return {redact_tree(str(k), redact): redact_tree(v, redact) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_tree(v, redact) for v in value]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact(str(value))[0]


def _dumps(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True).encode()


def _strings(tree: Any, path: tuple = ()) -> list[tuple[tuple, str]]:
    if isinstance(tree, str):
        return [(path, tree)]
    if isinstance(tree, dict):
        return [x for k, v in tree.items() for x in _strings(v, (*path, k))]
    if isinstance(tree, list):
        return [x for i, v in enumerate(tree) for x in _strings(v, (*path, i))]
    return []


def _set(tree: Any, path: tuple, value: Any) -> None:
    for key in path[:-1]:
        tree = tree[key]
    tree[path[-1]] = value


def cap_body(body: Any, limit: int) -> tuple[Any, dict | None]:
    """`body` cut to at most `limit` bytes of JSON, longest strings first, each
    cut saying how much it removed. Returns (body, cut) where `cut` is None when
    nothing was cut. A body that cannot be brought under the cap is replaced by
    a note saying so, never stored over the cap."""
    original = len(_dumps(body))
    if original <= limit:
        return body, None
    for _ in range(64):
        size = len(_dumps(body))
        if size <= limit:
            break
        strings = sorted(_strings(body), key=lambda x: len(x[1]), reverse=True)
        if not strings or len(strings[0][1]) <= 256:
            break
        path, text = strings[0]
        keep = max(128, len(text) - (size - limit) - 256)
        if keep >= len(text):
            keep = len(text) // 2
        _set(body, path, f"{text[:keep]} … [cut: {len(text) - keep} characters not stored; this run was over the per-run cap]")
    cut = {"original_bytes": original, "cap_bytes": limit}
    if len(_dumps(body)) > limit or not isinstance(body, dict):
        return {"not_stored": f"This run's content ({original} bytes) could not be cut under the per-run cap ({limit} bytes)."}, cut
    body["cut"] = cut
    return body, cut


@dataclass(frozen=True)
class RunSummary:
    id: str
    kind: str
    source_id: str
    event_id: str | None
    thread_id: str | None
    started_at: str
    finished_at: str | None
    status: str
    error: str | None
    size: int


class RunHistory:
    """The store. `root` is a directory it owns."""

    def __init__(
        self,
        root: Path,
        *,
        redact: Callable[[str], tuple[str, bool]] | None = None,
        now: Callable[[], datetime] | None = None,
        run_max_bytes: int = RUN_MAX_BYTES,
        total_max_bytes: int = TOTAL_MAX_BYTES,
    ) -> None:
        self.run_max_bytes = run_max_bytes
        self.total_max_bytes = total_max_bytes
        self.root = Path(root)
        self.blobs = self.root / "blobs"
        # Owner-only: the directory 0700, the database 0600, set on every open
        # so a store created before this rule (or under a loose umask) is fixed.
        self.blobs.mkdir(parents=True, exist_ok=True)
        for d in (self.root, self.blobs):
            os.chmod(d, 0o700)
        self.db = self.root / "runs.sqlite3"
        os.close(os.open(self.db, os.O_CREAT | os.O_RDWR, 0o600))
        os.chmod(self.db, 0o600)
        self._redact = redact or default_redactor()
        self._now = now or (lambda: datetime.now(UTC))
        self._lock = threading.Lock()
        with self._connect() as c:
            c.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db, timeout=10)
        conn.row_factory = sqlite3.Row
        # A deleted or purged run is overwritten with zeros, not left in a free
        # page where a copy of the file would still carry it. Per connection.
        conn.execute("PRAGMA secure_delete = ON")
        return conn

    # -- settings ---------------------------------------------------------

    def retention_days(self) -> int:
        with self._connect() as c:
            row = c.execute("SELECT value FROM settings WHERE key = 'retention_days'").fetchone()
        return int(row["value"]) if row else DEFAULT_RETENTION_DAYS

    def set_retention_days(self, days: int) -> None:
        if not 1 <= int(days) <= 3650:
            raise ValueError("retention must be between 1 and 3650 days")
        with self._connect() as c:
            c.execute("INSERT INTO settings (key, value) VALUES ('retention_days', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (str(int(days)),))

    # -- writes -----------------------------------------------------------

    def record(
        self,
        *,
        kind: str,
        source_id: str,
        body: dict,
        status: str,
        event_id: str | None = None,
        thread_id: str | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        error: str | None = None,
    ) -> str:
        """Store one run. Everything is redacted first; returns the run id."""
        run_id = uuid.uuid4().hex
        clean = redact_tree(body, self._redact)
        clean_error = self._redact(error)[0] if error else None
        clean, _cut = cap_body(clean, self.run_max_bytes)
        encoded = _dumps(clean)
        if self.used_bytes() + len(encoded) > self.total_max_bytes:
            logger.warning("run history: full (%d byte cap); run %s of %s recorded without its content", self.total_max_bytes, run_id, source_id)
            self._bump("not_stored_runs")
            clean = {"not_stored": f"The run history is full ({self.total_max_bytes // (1024 * 1024)} MB). This run's content was not stored. Delete the history or shorten the retention to make room."}
            encoded = _dumps(clean)
        data = encoded.decode()
        blob_name = f"{run_id}.json" if len(encoded) > INLINE_MAX else None
        started = (started_at or self._now()).isoformat()
        # One lock over the blob AND its row, the same lock delete_all and
        # purge hold over rows AND blobs: a delete can never land between the
        # two and leave a row naming a blob that is gone (or a stray blob).
        with self._lock, self._connect() as c:
            if blob_name:
                self._write_blob(blob_name, encoded)
            c.execute(
                "INSERT INTO runs (id, kind, source_id, event_id, thread_id, started_at, finished_at, status, error, size, body, blob) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, kind, source_id, event_id, thread_id, started, finished_at.isoformat() if finished_at else None, status, clean_error, len(encoded), None if blob_name else data, blob_name),
            )
        return run_id

    def _write_blob(self, name: str, data: bytes) -> None:
        fd, tmp = tempfile.mkstemp(dir=self.blobs, prefix=".", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.blobs / name)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def purge(self) -> int:
        """Delete runs older than the retention, with their blobs. Returns the count."""
        cutoff = (self._now() - timedelta(days=self.retention_days())).isoformat()
        with self._lock, self._connect() as c:
            rows = c.execute("SELECT id, blob FROM runs WHERE started_at < ?", (cutoff,)).fetchall()
            c.execute("DELETE FROM runs WHERE started_at < ?", (cutoff,))
            if rows:
                c.execute("DELETE FROM settings WHERE key = 'not_stored_runs'")
            for row in rows:
                if row["blob"]:
                    (self.blobs / row["blob"]).unlink(missing_ok=True)
        return len(rows)

    def delete_all(self) -> int:
        """Delete every run and every blob file. Returns how many runs."""
        with self._lock, self._connect() as c:
            n = c.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
            c.execute("DELETE FROM runs")
            c.execute("DELETE FROM settings WHERE key = 'not_stored_runs'")
            for f in self.blobs.iterdir():
                if f.is_file():
                    f.unlink(missing_ok=True)
        with self._lock, self._connect() as c:
            c.execute("VACUUM")
        return int(n)

    # -- reads ------------------------------------------------------------

    def list(self, *, kind: str | None = None, source_id: str | None = None, limit: int = 50) -> list[RunSummary]:
        where, args = [], []
        if kind:
            where.append("kind = ?")
            args.append(kind)
        if source_id:
            where.append("source_id = ?")
            args.append(source_id)
        sql = "SELECT id, kind, source_id, event_id, thread_id, started_at, finished_at, status, error, size FROM runs"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY started_at DESC LIMIT ?"
        with self._connect() as c:
            rows = c.execute(sql, (*args, int(limit))).fetchall()
        return [RunSummary(**dict(r)) for r in rows]

    def get(self, run_id: str) -> dict | None:
        """One run, with its full body."""
        with self._connect() as c:
            row = c.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        out = dict(row)
        out.pop("blob")
        try:
            raw = (self.blobs / row["blob"]).read_text() if row["blob"] else row["body"]
            out["body"] = json.loads(raw) if raw else None
        except (OSError, ValueError):
            # Gone (deleted under us, or by another process) or unreadable:
            # said in words, never a 500 and never a guess.
            out["body"] = {"withheld": BLOB_MISSING}
        return out

    def used_bytes(self) -> int:
        with self._connect() as c:
            return int(c.execute("SELECT COALESCE(SUM(size), 0) FROM runs").fetchone()[0])

    def _bump(self, key: str) -> None:
        with self._connect() as c:
            c.execute("INSERT INTO settings (key, value) VALUES (?, '1') ON CONFLICT(key) DO UPDATE SET value = CAST(value AS INTEGER) + 1", (key,))

    def not_stored_runs(self) -> int:
        with self._connect() as c:
            row = c.execute("SELECT value FROM settings WHERE key = 'not_stored_runs'").fetchone()
        return int(row["value"]) if row else 0

    def warning(self) -> str | None:
        """What the settings show about the cap, or None while there is room."""
        used, cap, refused = self.used_bytes(), self.total_max_bytes, self.not_stored_runs()
        mb = cap // (1024 * 1024)
        if refused:
            runs = "1 run was recorded without its content" if refused == 1 else f"{refused} runs were recorded without their content"
            return f"The run history is full ({mb} MB). {runs}. Delete the history or shorten the retention to make room."
        if used >= WARN_FRACTION * cap:
            return f"The run history is at {round(100 * used / cap)}% of its {mb} MB cap. When it is full, new runs are recorded without their content."
        return None

    def count(self) -> int:
        with self._connect() as c:
            return int(c.execute("SELECT COUNT(*) FROM runs").fetchone()[0])
