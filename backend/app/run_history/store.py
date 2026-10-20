"""A durable, local store of runs: inputs, tool calls and results, outputs.

GATED: a run can carry mail and calendar content, so these are the guarantees,
each tested (tests/run_history):

  * FULL CONTENT, WITHIN CAPS. Not cut at 10 KB as the run_events table cuts
    trace content. A body above INLINE_MAX bytes is written to its own file
    under `blobs/`, atomically, and the row names it. One run is capped at
    RUN_MAX_BYTES: past it the longest strings are cut, each cut says so, and
    the body carries `cut`. Its error is cut to ERROR_MAX and its ids to
    ID_MAX, and they count toward the caps. The whole history is capped at
    TOTAL_MAX_BYTES, hard: past it a run is not stored at all (only a counter
    moves), and `warning()` (shown in Settings) says how many; it warns from
    WARN_FRACTION of the cap.
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
  * PROVENANCE. Every stored message carries `provenance` (trigger, user,
    assistant, system, untrusted_tool_output, unknown), set from its type by
    `with_provenance`, so 007's replay can keep tool output as data.

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
#: An error message is cut to this many characters, an id to ID_MAX.
ERROR_MAX = 4096
ID_MAX = 256
#: The run kind whose threads the ledger tracks (recorder.AUTOMATION).
AUTOMATION_KIND = "automation"

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
    blob TEXT,
    owner_id TEXT
);
CREATE INDEX IF NOT EXISTS runs_source ON runs (kind, source_id, started_at);
CREATE INDEX IF NOT EXISTS runs_started ON runs (started_at);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
-- The authoritative ledger of the threads the trigger engine created (noted
-- at creation, and from every automation run that names one). Deleting the
-- automations' threads works from THIS, never from a request or only from the
-- rule map; a row stays until its thread is really gone (pending_delete=1
-- with last_error after a failure), so a failed delete is retried.
CREATE TABLE IF NOT EXISTS automation_threads (
    thread_id TEXT PRIMARY KEY,
    rule_id TEXT,
    first_seen TEXT NOT NULL,
    pending_delete INTEGER NOT NULL DEFAULT 0,
    last_error TEXT
);
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


def _text_parts(value: list | tuple) -> list[int]:
    """Indexes of content parts carrying text ({"type": "text", "text": ...})."""
    return [i for i, v in enumerate(value) if isinstance(v, dict) and isinstance(v.get("text"), str)]


def redact_tree(value: Any, redact: Callable[[str], tuple[str, bool]]) -> Any:
    """Every string in `value`, at any depth (keys included), redacted.

    * A key that fails redaction becomes a DISTINCT withheld key ("… #n"), so
      two withheld keys never collapse into one and drop a value.
    * A message's text parts are also redacted JOINED: a secret split across
      two parts is found. When the joined text redacts differently from the
      parts one by one, the redacted joined text goes in the first part and the
      others are emptied (marked `merged_for_redaction`)."""
    if isinstance(value, str):
        return redact(value)[0]
    if isinstance(value, dict):
        out: dict = {}
        for i, (k, v) in enumerate(value.items()):
            key, ok = redact(str(k))
            if not ok or key in out:
                key = f"{WITHHELD} #{i}"
            out[key] = redact_tree(v, redact)
        return out
    if isinstance(value, (list, tuple)):
        items = [redact_tree(v, redact) for v in value]
        idx = _text_parts(value)
        if len(idx) >= 2:
            joined, ok = redact("".join(value[i]["text"] for i in idx))
            separately = "".join(items[i]["text"] for i in idx if isinstance(items[i].get("text"), str))
            if not ok or joined != separately:
                for n, i in enumerate(idx):
                    items[i] = {**items[i], "text": joined if n == 0 else "", "merged_for_redaction": True}
        return items
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact(str(value))[0]


def _utc(when: datetime) -> datetime:
    """Aware and in UTC; a naive time is taken as UTC."""
    return when.replace(tzinfo=UTC) if when.tzinfo is None else when.astimezone(UTC)


def _parse(text: str) -> datetime:
    return _utc(datetime.fromisoformat(text))


def _cut_text(text: str, limit: int) -> str:
    return text if len(text) <= limit else f"{text[:limit]} … [cut: {len(text) - limit} characters]"


def _shred(path: Path) -> None:
    """Overwrite a file with zeros, then unlink it. On a copy-on-write or
    wear-levelled disk (APFS, SSDs) the old blocks may survive anyway: this
    removes the easy copy, it does not promise forensic erasure."""
    try:
        size = path.stat().st_size
        with open(path, "r+b") as fh:
            fh.write(b"\0" * size)
            fh.flush()
            os.fsync(fh.fileno())
    except OSError:
        pass
    path.unlink(missing_ok=True)


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


# -- provenance (for 007 replay) ------------------------------------------------
#
# Every stored message says where its content came from, set HERE from the
# message's own type, never taken from the message: replay must be able to treat
# a tool's output as untrusted data even if that output claims otherwise.
TRIGGER = "trigger"  # the prompt an automation injected, exactly its rule's text
#: The injected prompt with EVENT text rendered into it (a mail subject, a
#: session's message): written by whoever sent that event, so untrusted.
TRIGGER_WITH_EVENT = "trigger_with_untrusted_event"
#: A person's message that arrived in the thread during an automation's turn.
CONCURRENT_USER = "user_concurrent"
USER = "user"  # a person's message
ASSISTANT = "assistant"  # the model's own output, tool calls included
SYSTEM = "system"
UNTRUSTED_TOOL_OUTPUT = "untrusted_tool_output"  # what a tool returned: mail, pages, files
UNKNOWN = "unknown"  # a message of a type not recognised: said, not guessed

_ROLE_PROVENANCE = {
    "human": USER,
    "user": USER,
    "ai": ASSISTANT,
    "assistant": ASSISTANT,
    "AIMessageChunk": ASSISTANT,
    "system": SYSTEM,
    "tool": UNTRUSTED_TOOL_OUTPUT,
    "function": UNTRUSTED_TOOL_OUTPUT,
}


def with_provenance(body: Any, *, first_human: str = USER) -> Any:
    """`body` with a `provenance` on each of its `messages`, by type. The first
    human message is labelled `first_human` (TRIGGER for an automation run,
    whose turn starts with the injected prompt)."""
    if not isinstance(body, dict) or not isinstance(body.get("messages"), list):
        return body
    out, seen_human = [], False
    for m in body["messages"]:
        if not isinstance(m, dict):
            out.append({"provenance": UNKNOWN, "content": m})
            continue
        kind = m.get("type") or m.get("role")
        label = _ROLE_PROVENANCE.get(str(kind), UNKNOWN)
        if label == USER:
            if not seen_human:
                label, seen_human = first_human, True
            elif first_human in (TRIGGER, TRIGGER_WITH_EVENT):
                label = CONCURRENT_USER
        out.append({**m, "provenance": label})
    return {**body, "messages": out}


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
    #: Who the run belongs to (ownership.can_access decides who may see it).
    owner_id: str | None = None


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
            # A store created before owners were stored: add the column. Its
            # rows keep a NULL owner, which the ownership rule gives to the
            # owner account only (app/gateway/ownership.py).
            if "owner_id" not in {r["name"] for r in c.execute("PRAGMA table_info(runs)")}:
                c.execute("ALTER TABLE runs ADD COLUMN owner_id TEXT")
        self._clear_stale_tmp()

    def _clear_stale_tmp(self, older_than: float = 3600.0) -> None:
        """A blob write interrupted by a crash leaves `.<x>.tmp`: shred it."""
        now = datetime.now().timestamp()
        for f in self.blobs.glob(".*.tmp"):
            try:
                if now - f.stat().st_mtime > older_than:
                    _shred(f)
            except OSError:
                pass

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
        first_human: str = USER,
        owner_id: str | None = None,
    ) -> str:
        """Store one run. Every message gets its provenance and everything is
        redacted first; returns the run id."""
        run_id = uuid.uuid4().hex
        # The ledger first: whatever happens to this run's content, the thread
        # the engine ran in is known, so it can be deleted later.
        if kind == AUTOMATION_KIND and thread_id:
            self.note_thread(thread_id, source_id)
        clean = redact_tree(with_provenance(body, first_human=first_human), self._redact)
        # Every column is redacted and capped, not only the body.
        clean_error = _cut_text(self._redact(error)[0], ERROR_MAX) if error else None
        source_id, event_id, thread_id = (_cut_text(self._redact(v)[0], ID_MAX) if v else v for v in (source_id, event_id, thread_id))
        clean, _cut = cap_body(clean, self.run_max_bytes)
        encoded = _dumps(clean)
        extra = sum(len(v or "") for v in (clean_error, source_id, event_id, thread_id, kind, status))
        if self.used_bytes() + len(encoded) + extra > self.total_max_bytes:
            # HARD cap: nothing is written but a counter (no note row per
            # refused run, which would grow without bound). The settings say
            # how many runs were not stored. Returns "" (no run id).
            logger.warning("run history: full (%d byte cap); a run of %s was not stored", self.total_max_bytes, source_id)
            self._bump("not_stored_runs")
            return ""
        data = encoded.decode()
        blob_name = f"{run_id}.json" if len(encoded) > INLINE_MAX else None
        # Stored in UTC, so stored times compare as times.
        started = _utc(started_at or self._now()).isoformat()
        # One lock over the blob AND its row, the same lock delete_all and
        # purge hold over rows AND blobs: a delete can never land between the
        # two and leave a row naming a blob that is gone (or a stray blob).
        with self._lock, self._connect() as c:
            if blob_name:
                self._write_blob(blob_name, encoded)
            c.execute(
                "INSERT INTO runs (id, kind, source_id, event_id, thread_id, started_at, finished_at, status, error, size, body, blob, owner_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, kind, source_id, event_id, thread_id, started, _utc(finished_at).isoformat() if finished_at else None, status, clean_error, len(encoded) + extra, None if blob_name else data, blob_name, owner_id),
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
        cutoff = _utc(self._now()) - timedelta(days=self.retention_days())
        with self._lock, self._connect() as c:
            # Compared as datetimes (UTC), not as strings: a row stamped with
            # another offset, or by an older version, still compares right.
            rows = [r for r in c.execute("SELECT id, blob, started_at, thread_id FROM runs").fetchall() if _parse(r["started_at"]) < cutoff]
            c.executemany("DELETE FROM runs WHERE id = ?", [(r["id"],) for r in rows])
            # The ledger keeps how old each thread's content is, after the runs
            # that showed it are gone (threads_past_retention reads it).
            c.executemany(
                "UPDATE automation_threads SET first_seen = ? WHERE thread_id = ? AND first_seen > ?",
                [(_parse(r["started_at"]).isoformat(), r["thread_id"], _parse(r["started_at"]).isoformat()) for r in rows if r["thread_id"]],
            )
            if rows:
                c.execute("DELETE FROM settings WHERE key = 'not_stored_runs'")
            for row in rows:
                if row["blob"]:
                    _shred(self.blobs / row["blob"])
        return len(rows)

    def delete_all(self) -> int:
        """Delete every run and every blob file. Returns how many runs."""
        with self._lock, self._connect() as c:
            n = c.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
            c.execute("DELETE FROM runs")
            c.execute("DELETE FROM settings WHERE key = 'not_stored_runs'")
            for f in self.blobs.iterdir():
                if f.is_file():
                    _shred(f)
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
        sql = "SELECT id, kind, source_id, event_id, thread_id, started_at, finished_at, status, error, size, owner_id FROM runs"
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

    def thread_ids(self, *, kind: str | None = None) -> set[str]:
        """Every thread a stored run names (of `kind`, when given)."""
        sql = "SELECT DISTINCT thread_id FROM runs WHERE thread_id IS NOT NULL" + (" AND kind = ?" if kind else "")
        with self._connect() as c:
            return {r[0] for r in c.execute(sql, (kind,) if kind else ()).fetchall()}

    # -- the ledger of automation threads ----------------------------------

    def note_thread(self, thread_id: str, rule_id: str | None) -> None:
        with self._connect() as c:
            c.execute(
                "INSERT INTO automation_threads (thread_id, rule_id, first_seen) VALUES (?, ?, ?) ON CONFLICT(thread_id) DO NOTHING",
                (thread_id, rule_id, _utc(self._now()).isoformat()),
            )

    def ledger_threads(self) -> dict[str, dict]:
        with self._connect() as c:
            return {r["thread_id"]: dict(r) for r in c.execute("SELECT * FROM automation_threads").fetchall()}

    def mark_threads_pending(self, thread_ids) -> None:
        with self._connect() as c:
            c.executemany("UPDATE automation_threads SET pending_delete = 1 WHERE thread_id = ?", [(t,) for t in thread_ids])

    def thread_gone(self, thread_id: str) -> None:
        with self._connect() as c:
            c.execute("DELETE FROM automation_threads WHERE thread_id = ?", (thread_id,))

    def thread_failed(self, thread_id: str, error: str) -> None:
        with self._connect() as c:
            c.execute("UPDATE automation_threads SET pending_delete = 1, last_error = ? WHERE thread_id = ?", (error[:500], thread_id))

    def threads_to_sweep(self, mapped: set[str]) -> list[str]:
        """Ledger threads to delete now: marked pending (a delete that failed or
        was interrupted), or no longer named by any stored run (retention
        purged them) and not the thread of a rule that still exists."""
        with self._connect() as c:
            pending = {r[0] for r in c.execute("SELECT thread_id FROM automation_threads WHERE pending_delete = 1")}
            orphans = {r[0] for r in c.execute("SELECT thread_id FROM automation_threads WHERE thread_id NOT IN (SELECT thread_id FROM runs WHERE thread_id IS NOT NULL)")}
        return sorted(pending | (orphans - mapped))

    def threads_past_retention(self) -> set[str]:
        """Ledger threads holding content older than the retention: the
        thread's own start (when the ledger first saw it) or its oldest stored
        run is past the window. A thread holds nothing older than its start."""
        cutoff = _utc(self._now()) - timedelta(days=self.retention_days())
        with self._connect() as c:
            rows = c.execute("SELECT t.thread_id, t.first_seen, MIN(r.started_at) AS oldest_run FROM automation_threads t LEFT JOIN runs r ON r.thread_id = t.thread_id GROUP BY t.thread_id").fetchall()
        out = set()
        for r in rows:
            times = [_parse(v) for v in (r["first_seen"], r["oldest_run"]) if v]
            if times and min(times) < cutoff:
                out.add(r["thread_id"])
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
            runs = "1 run was not stored" if refused == 1 else f"{refused} runs were not stored"
            return f"The run history is full ({mb} MB). {runs}. Delete the history or shorten the retention to make room."
        if used >= WARN_FRACTION * cap:
            return f"The run history is at {round(100 * used / cap)}% of its {mb} MB cap. When it is full, new runs are not stored."
        return None

    def count(self) -> int:
        with self._connect() as c:
            return int(c.execute("SELECT COUNT(*) FROM runs").fetchone()[0])
