"""A durable, local store of runs: inputs, tool calls and results, outputs.

GATED: a run can carry mail and calendar content, so these are the guarantees,
each tested (tests/run_history):

  * FULL CONTENT. No truncation (the run_events table cuts trace content at
    10 KB). A body above INLINE_MAX bytes is written to its own file under
    `blobs/`, atomically, and the row names it.
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

Thread-safe: one connection per call, and SQLite's own locking. The trigger
engine records from its worker thread; the routers read from the event loop.
"""

from __future__ import annotations

import json
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

#: Bodies larger than this (bytes of JSON) go to a blob file, not the row.
INLINE_MAX = 64 * 1024
DEFAULT_RETENTION_DAYS = 30
#: What a string is stored as when it could not be redacted.
WITHHELD = "[Withheld: could not be redacted]"

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

    def __init__(self, root: Path, *, redact: Callable[[str], tuple[str, bool]] | None = None, now: Callable[[], datetime] | None = None) -> None:
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
        data = json.dumps(clean, ensure_ascii=False, sort_keys=True)
        encoded = data.encode()
        blob_name = None
        if len(encoded) > INLINE_MAX:
            blob_name = f"{run_id}.json"
            self._write_blob(blob_name, encoded)
        started = (started_at or self._now()).isoformat()
        with self._lock, self._connect() as c:
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
        for row in rows:
            if row["blob"]:
                (self.blobs / row["blob"]).unlink(missing_ok=True)
        return len(rows)

    def delete_all(self) -> int:
        """Delete every run and every blob file. Returns how many runs."""
        with self._lock, self._connect() as c:
            n = c.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
            c.execute("DELETE FROM runs")
        for f in self.blobs.iterdir():
            if f.is_file():
                f.unlink(missing_ok=True)
        with self._connect() as c:
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
        raw = (self.blobs / row["blob"]).read_text() if row["blob"] else row["body"]
        out.pop("blob")
        out["body"] = json.loads(raw) if raw else None
        return out

    def count(self) -> int:
        with self._connect() as c:
            return int(c.execute("SELECT COUNT(*) FROM runs").fetchone()[0])
