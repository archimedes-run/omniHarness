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
  * ENCRYPTED AT REST. Body, blob and error are sealed (AES-256-GCM) with the
    run's own data key, after redaction; the data keys are kept, wrapped by a
    master key, in a key store OUTSIDE this database. Deleting or expiring a
    run destroys its key; delete-all and a purge that empties the store also
    rotate the master key (crypto.py states exactly what that covers).
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

from app.run_history.crypto import CannotDecrypt, StoreKey

logger = logging.getLogger(__name__)

#: Bodies larger than this (bytes of JSON) go to a blob file, not the row.
INLINE_MAX = 64 * 1024
DEFAULT_RETENTION_DAYS = 30
#: What a string is stored as when it could not be redacted.
WITHHELD = "[Withheld: could not be redacted]"
#: A run's content sealed under a key that has since been rotated (or altered).
UNREADABLE = "[Withheld: this run's content cannot be decrypted with the store's current key]"
#: A run's body when its blob file is missing or unreadable.
BLOB_MISSING = "[Withheld: this run's stored content is missing or unreadable]"
#: One run's stored body is cut to this (bytes of JSON): the longest strings
#: are shortened first, each saying how much was cut, and the body says so.
RUN_MAX_BYTES = 2 * 1024 * 1024
#: The whole history's cap. Past it a run is recorded WITHOUT its content, and
#: the settings say so; at WARN_FRACTION of it the settings warn.
TOTAL_MAX_BYTES = 512 * 1024 * 1024
WARN_FRACTION = 0.9
#: A data key younger than this is never treated as an orphan, and its
#: presence blocks a purge's master-key rotation: a record on another worker
#: may have written it and not yet committed its row.
KEY_GRACE_SECONDS = 600
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
-- The trigger engine's signed turn ids already accepted once. Shared by every
-- worker (one database), so a replay to another worker fails the insert.
CREATE TABLE IF NOT EXISTS consumed_turn_ids (turn_id TEXT PRIMARY KEY, at TEXT NOT NULL);
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
    last_error TEXT,
    -- Why a delete is pending: 'explicit' (the person asked: delete it whole)
    -- or 'retention' (re-checked for a person's messages before deleting).
    delete_reason TEXT,
    -- A retention trim that failed or was cut short: retried as a TRIM, never
    -- turned into a delete.
    trim_pending INTEGER NOT NULL DEFAULT 0
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
#: A person's message that arrived in the thread during an automation's turn
#: (only when the server tagged it as a user turn).
CONCURRENT_USER = "user_concurrent"
#: A human-typed message during an automation's turn that is NOT tagged as a
#: person's: harness-injected (summary, image, reminder) or unverifiable.
UNVERIFIED_HUMAN = "untrusted_injected_or_unverified"


def _is_tagged_user_turn(message: dict) -> bool:
    """The server's user-turn tag: the security baseline's one test,
    lineage.is_user_turn (a human message services.normalize_input tagged on
    receipt). A message with a harness `name` is never a person's."""
    if message.get("name"):
        return False
    from app.policy.lineage import is_user_turn

    return bool(is_user_turn(message))


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
                # Later human messages in an automation turn: a person writing
                # mid-run, OR harness middleware (summaries, viewed images,
                # todo reminders, preview errors) which also arrive as human
                # messages. Only a server-set user-turn tag can tell them
                # apart; without it, never claim a person wrote it.
                label = CONCURRENT_USER if _is_tagged_user_turn(m) else UNVERIFIED_HUMAN
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
        key: StoreKey | None = None,
    ) -> None:
        # Encryption at rest (crypto.py). Raises KeyRefused on an unsafe key
        # file: the store does not open rather than store content in the clear.
        self.key = key or StoreKey()
        self.key.key()
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
            # WAL, so readers never block the recorder; every purge and delete
            # ends with a TRUNCATE checkpoint so the WAL file holds no copy of
            # what was removed (see _flush_wal).
            c.execute("PRAGMA journal_mode = WAL")
            c.executescript(_SCHEMA)
            # A store created before owners were stored: add the column. Its
            # rows keep a NULL owner, which the ownership rule gives to the
            # owner account only (app/gateway/ownership.py).
            if "owner_id" not in {r["name"] for r in c.execute("PRAGMA table_info(runs)")}:
                c.execute("ALTER TABLE runs ADD COLUMN owner_id TEXT")
            ledger_cols = {r["name"] for r in c.execute("PRAGMA table_info(automation_threads)")}
            if "delete_reason" not in ledger_cols:
                c.execute("ALTER TABLE automation_threads ADD COLUMN delete_reason TEXT")
            if "trim_pending" not in ledger_cols:
                c.execute("ALTER TABLE automation_threads ADD COLUMN trim_pending INTEGER NOT NULL DEFAULT 0")
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
        blob_name = f"{run_id}.json" if len(encoded) > INLINE_MAX else None
        # Stored in UTC, so stored times compare as times.
        started = _utc(started_at or self._now()).isoformat()
        # One lock over the data key, the blob AND the row, the same lock
        # delete_all and purge hold over rows, blobs and keys: a delete (or a
        # key rotation) can never land between them.
        with self._lock, self._connect() as c:
            # Sealed AFTER redaction: content never reaches the disk in the
            # clear. This run's own data key is wrapped into the key store
            # (outside this database) BEFORE the row exists: deleting the run
            # destroys it.
            dek = self.key.new_data_key(run_id)
            data = None if blob_name else self.key.seal_with(dek, encoded, f"{run_id}|body")
            sealed_blob = self.key.seal_with(dek, encoded, f"{run_id}|blob").encode() if blob_name else None
            clean_error = self.key.seal_with(dek, clean_error.encode(), f"{run_id}|error") if clean_error else None
            # Row FIRST, blob second, one transaction: a failed insert never
            # leaves a blob; a failed blob write rolls the row back.
            c.execute(
                "INSERT INTO runs (id, kind, source_id, event_id, thread_id, started_at, finished_at, status, error, size, body, blob, owner_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, kind, source_id, event_id, thread_id, started, _utc(finished_at).isoformat() if finished_at else None, status, clean_error, len(encoded) + extra, data, blob_name, owner_id),
            )
            if blob_name:
                self._write_blob(blob_name, sealed_blob)
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
            # A blob no row names (a crash between the two, or an older
            # version's write order) is shredded too, never kept forever.
            named = {r[0] for r in c.execute("SELECT blob FROM runs WHERE blob IS NOT NULL")}
            for f in self.blobs.glob("*.json"):
                if f.name not in named:
                    _shred(f)
            # Crypto-shred the expired runs: their data keys are destroyed.
            live = {r[0] for r in c.execute("SELECT id FROM runs")}
            self.key.destroy([r["id"] for r in rows])
            # And keys no row names, but ONLY those older than KEY_GRACE: a
            # record on another worker writes its key before its row commits,
            # so a young key without a row may be a run being recorded now.
            self.key.destroy(self.key.key_ids(older_than=KEY_GRACE_SECONDS) - live)
            if rows and not live:
                # Nothing left that needs the master key: rotate it too, but
                # only if no record is in flight anywhere (no key younger than
                # the grace), the check and the rotation in one key-store
                # transaction (rotate_if_quiet).
                self.key.rotate_if_quiet(KEY_GRACE_SECONDS)
        self._flush_wal()
        return len(rows)

    def delete_run(self, run_id: str) -> bool:
        """Delete one run: its row, its blob, and (crypto-shredding) its data
        key. Returns whether it existed."""
        with self._lock, self._connect() as c:
            row = c.execute("SELECT blob FROM runs WHERE id = ?", (run_id,)).fetchone()
            c.execute("DELETE FROM runs WHERE id = ?", (run_id,))
            if row is not None and row["blob"]:
                _shred(self.blobs / row["blob"])
            self.key.destroy([run_id])
        self._flush_wal()
        return row is not None

    def _flush_wal(self) -> None:
        """Copy the WAL into the (secure_delete) database and truncate it to
        zero bytes. What can still remain, said plainly: blocks the filesystem
        or SSD kept from before (copy-on-write, wear levelling) and any backup
        or snapshot of this directory; this is deletion, not forensic erasure."""
        with self._lock, self._connect() as c:
            c.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def delete_all(self) -> int:
        """Delete every run and every blob file. Returns how many runs."""
        with self._lock, self._connect() as c:
            n = c.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
            c.execute("DELETE FROM runs")
            c.execute("DELETE FROM settings WHERE key = 'not_stored_runs'")
            for f in self.blobs.iterdir():
                if f.is_file():
                    _shred(f)
            # Crypto-shredding, under the same lock (no record can take a key
            # in between): every data key is destroyed and the master key
            # replaced, so what may survive the delete (SSD blocks, WAL or
            # journal pages, an old copy of the database) cannot be opened.
            self.key.rotate()
        with self._lock, self._connect() as c:
            c.execute("VACUUM")
        self._flush_wal()
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
        return [RunSummary(**{**dict(r), "error": self._open_error(r["id"], r["error"])}) for r in rows]

    def _open_error(self, run_id: str, sealed: str | None) -> str | None:
        if not sealed:
            return None
        try:
            return self.key.open_for(run_id, sealed, f"{run_id}|error").decode()
        except CannotDecrypt:
            return UNREADABLE

    # -- once-only turn ids ---------------------------------------------------

    def consume_turn_id(self, turn_id: str) -> bool:
        """True the first time `turn_id` is seen by ANY worker (one shared
        database, a primary key); False on every later attempt."""
        try:
            with self._connect() as c:
                c.execute("INSERT INTO consumed_turn_ids (turn_id, at) VALUES (?, ?)", (turn_id, datetime.now(UTC).isoformat()))
            return True
        except sqlite3.IntegrityError:
            return False

    def get(self, run_id: str) -> dict | None:
        """One run, with its full body."""
        with self._connect() as c:
            row = c.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        out = dict(row)
        out.pop("blob")
        out["error"] = self._open_error(run_id, row["error"])
        try:
            if row["blob"]:
                plain = self.key.open_for(run_id, (self.blobs / row["blob"]).read_text(), f"{run_id}|blob")
            else:
                plain = self.key.open_for(run_id, row["body"], f"{run_id}|body") if row["body"] else b""
            out["body"] = json.loads(plain) if plain else None
        except CannotDecrypt:
            out["body"] = {"withheld": UNREADABLE}
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
        """The person asked to delete these threads ("Delete run history"):
        an EXPLICIT delete, finished whole even if it has to be retried."""
        with self._connect() as c:
            c.executemany("UPDATE automation_threads SET pending_delete = 1, delete_reason = 'explicit' WHERE thread_id = ?", [(t,) for t in thread_ids])

    def thread_gone(self, thread_id: str) -> None:
        with self._connect() as c:
            c.execute("DELETE FROM automation_threads WHERE thread_id = ?", (thread_id,))

    def thread_failed(self, thread_id: str, error: str, *, reason: str = "retention") -> None:
        """A DELETE failed. An explicit delete stays explicit; otherwise it is
        a retention delete, re-checked for a person's messages on retry."""
        with self._connect() as c:
            c.execute(
                "UPDATE automation_threads SET pending_delete = 1, last_error = ?, delete_reason = COALESCE(delete_reason, ?) WHERE thread_id = ?",
                (error[:500], reason, thread_id),
            )

    def trim_failed(self, thread_id: str, error: str) -> None:
        """A retention TRIM failed or was cut short: retried as a trim. Never
        sets pending_delete, so a failed trim can never become a delete."""
        with self._connect() as c:
            c.execute("UPDATE automation_threads SET trim_pending = 1, last_error = ? WHERE thread_id = ?", (error[:500], thread_id))

    def trim_done(self, thread_id: str) -> None:
        with self._connect() as c:
            c.execute("UPDATE automation_threads SET trim_pending = 0, last_error = NULL WHERE thread_id = ?", (thread_id,))

    def explicit_deletes(self) -> set[str]:
        with self._connect() as c:
            return {r[0] for r in c.execute("SELECT thread_id FROM automation_threads WHERE pending_delete = 1 AND delete_reason = 'explicit'")}

    def threads_to_sweep(self, mapped: set[str]) -> list[str]:
        """Ledger threads to delete now: marked pending (a delete that failed or
        was interrupted), or no longer named by any stored run (retention
        purged them) and not the thread of a rule that still exists."""
        with self._connect() as c:
            pending = {r[0] for r in c.execute("SELECT thread_id FROM automation_threads WHERE pending_delete = 1 OR trim_pending = 1")}
            orphans = {r[0] for r in c.execute("SELECT thread_id FROM automation_threads WHERE thread_id NOT IN (SELECT thread_id FROM runs WHERE thread_id IS NOT NULL)")}
        return sorted(pending | (orphans - mapped))

    def retention_cutoff(self) -> datetime:
        return _utc(self._now()) - timedelta(days=self.retention_days())

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
