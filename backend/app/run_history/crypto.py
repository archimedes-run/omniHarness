"""Encryption at rest for the run history: envelope encryption, per-run keys.

WHAT IS ENCRYPTED. Every run's content: its body (prompt, messages, tool calls
and results, the reply, event fields), its blob file, and its error. Each run
has its own random 256-bit DATA KEY; each value is sealed with it (AES-256-GCM,
fresh 96-bit nonce, authenticated with the run id and the field name, so a
ciphertext moved to another row or field fails to open). What stays clear is
what listing and retention need: ids, kind, rule id, thread id, timestamps,
status, sizes, owner. Redaction runs BEFORE encryption.

TWO KEY FILES, both OUTSIDE the run database, the project tree, the gateway's
data dir and every agent-reachable mount, in one 0700 directory:
  * the MASTER key, ``$OMNI_HARNESS_RUN_STORE_KEY_FILE``, else
    ``~/.omni-harness-secrets/run_store.key`` (0600);
  * the KEY STORE beside it, ``run_store_keys.sqlite3`` (0600): each run's
    data key, WRAPPED by the master key, under the run's id.
The run database holds only ciphertext; its rows name their key by run id.
Never in config.yaml, .env or the database. Both are created on first use. The
store REFUSES to open (the run history is then unavailable, and the routes say
so) when either file's mode is wider than 0600 or the directory sits under the
project or the data dir. The master key is registered as a known secret.

CRYPTO-SHREDDING.
  * Deleting or expiring a run DESTROYS its wrapped data key (secure_delete in
    the key store). A copy of the run database taken before, opened with the
    current master key and the current key store, cannot open that run; the
    other runs still open.
  * "Delete run history", and a purge that leaves no run, also ROTATE the
    master key (a new key renamed over the old file, whose bytes are first
    overwritten): nothing sealed before can be opened with the keys the store
    then has.

RESIDUALS, stated. A backup holding BOTH an old copy of the run database AND an
old copy of the key store can still open a deleted run until the master key is
next rotated (delete-all, or a purge that empties the store). Hence the rule:
the key directory is never backed up together with the run database (spec).
Overwriting a file does not erase its old blocks on a copy-on-write or
wear-levelled disk (APFS, SSDs): rotation, not overwriting, is the control.
"""

from __future__ import annotations

import base64
import logging
import os
import sqlite3
import stat
import threading
import time
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger(__name__)

KEY_FILE_ENV = "OMNI_HARNESS_RUN_STORE_KEY_FILE"
KEY_STORE_NAME = "run_store_keys.sqlite3"
PREFIX = "enc1:"


class KeyRefused(RuntimeError):
    """The key files are unsafe; the run history will not open."""


class CannotDecrypt(Exception):
    """No key for this run any more (deleted, expired, rotated), or altered."""


def default_key_path() -> Path:
    configured = os.environ.get(KEY_FILE_ENV)
    if configured:
        return Path(configured).expanduser()
    return Path(os.environ.get("HOME") or Path.home()) / ".omni-harness-secrets" / "run_store.key"


def forbidden_roots() -> list[Path]:
    """Where the keys must never live: the project tree, the data dir (every
    thread's sandbox files live under it), the skills dir and every host path
    config.yaml mounts into the agent sandbox. So no agent file tool can ever
    reach them."""
    roots = [Path(__file__).resolve().parents[3]]
    try:
        from omniharness.config.paths import get_paths

        roots.append(get_paths().base_dir.resolve())
    except Exception:  # noqa: BLE001 — no paths configured: the project root still applies
        pass
    try:
        from omniharness.config import get_app_config

        config = get_app_config()
        roots.append(Path(config.skills.get_skills_path()).resolve())
        for mount in getattr(config.sandbox, "mounts", None) or []:
            roots.append(Path(mount.host_path).expanduser().resolve())
    except Exception:  # noqa: BLE001 — no config: the roots above still apply
        pass
    return roots


def _seal(key: bytes, plain: bytes, aad: str) -> bytes:
    nonce = os.urandom(12)
    return nonce + AESGCM(key).encrypt(nonce, plain, aad.encode())


def _open(key: bytes, blob: bytes, aad: str) -> bytes:
    try:
        return AESGCM(key).decrypt(blob[:12], blob[12:], aad.encode())
    except InvalidTag as exc:
        raise CannotDecrypt("sealed under another key, or altered") from exc


class StoreKey:
    """The master key file and the key store of wrapped per-run data keys.
    Thread-safe, and safe across workers (files re-read when they change)."""

    def __init__(self, path: Path | None = None, *, forbidden: list[Path] | None = None) -> None:
        self.path = Path(path or default_key_path())
        self.store_path = self.path.with_name(KEY_STORE_NAME)
        self._forbidden = forbidden if forbidden is not None else forbidden_roots()
        self._lock = threading.Lock()
        self._cached: tuple[tuple[float, int], bytes] | None = None
        self._check_location()

    # -- files ----------------------------------------------------------------

    def _check_location(self) -> None:
        resolved = self.path.expanduser().resolve().parent
        for root in self._forbidden:
            if resolved == root or root in resolved.parents:
                raise KeyRefused(f"The run store key files must not be inside {root} (the project or the data dir, which agents can reach). Move them, e.g. to ~/.omni-harness-secrets/, and set {KEY_FILE_ENV}.")

    def _check_mode(self, path: Path) -> None:
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & 0o077:
            raise KeyRefused(f"The run store key file {path} has mode {oct(mode)}; it must be 0600 (chmod 600 it).")

    def _write_new_master(self, target: Path) -> None:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(base64.b64encode(AESGCM.generate_key(bit_length=256)))
            fh.flush()
            os.fsync(fh.fileno())

    def _master(self) -> bytes:
        if not self.path.exists():
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(self.path.parent, 0o700)
            try:
                self._write_new_master(self.path)
                logger.info("run history: created its master key at %s (0600)", self.path)
            except FileExistsError:
                pass  # another worker created it first
        self._check_mode(self.path)
        st = self.path.stat()
        sig = (st.st_mtime, st.st_ino)
        if self._cached is None or self._cached[0] != sig:
            raw = self.path.read_bytes().strip()
            key = base64.b64decode(raw)
            if len(key) != 32:
                raise KeyRefused(f"The run store key file {self.path} does not hold a 256-bit key.")
            from omniharness.utils.known_secrets import register_secret

            register_secret(raw.decode(), "run-store-key")
            self._cached = (sig, key)
        return self._cached[1]

    def _db(self) -> sqlite3.Connection:
        new = not self.store_path.exists()
        if new:
            os.close(os.open(self.store_path, os.O_CREAT | os.O_RDWR, 0o600))
        self._check_mode(self.store_path)
        conn = sqlite3.connect(self.store_path, timeout=10)
        # A destroyed key is zeroed in the file; the rollback journal is
        # deleted at each commit (no WAL holding old pages).
        conn.execute("PRAGMA secure_delete = ON")
        conn.execute("PRAGMA journal_mode = DELETE")
        conn.execute("CREATE TABLE IF NOT EXISTS data_keys (key_id TEXT PRIMARY KEY, wrapped BLOB NOT NULL, created REAL NOT NULL DEFAULT 0)")
        if "created" not in {r[1] for r in conn.execute("PRAGMA table_info(data_keys)")}:
            conn.execute("ALTER TABLE data_keys ADD COLUMN created REAL NOT NULL DEFAULT 0")
        return conn

    def key(self) -> bytes:
        """The master key (created on first use). Also checks the key store."""
        with self._lock:
            master = self._master()
            with self._db():
                pass
            return master

    # -- per-run data keys -------------------------------------------------------

    def new_data_key(self, key_id: str) -> bytes:
        dek = AESGCM.generate_key(bit_length=256)
        with self._lock:
            wrapped = _seal(self._master(), dek, f"data-key|{key_id}")
            with self._db() as c:
                c.execute("INSERT INTO data_keys (key_id, wrapped, created) VALUES (?, ?, ?)", (key_id, wrapped, time.time()))
        return dek

    def data_key(self, key_id: str) -> bytes:
        with self._lock:
            master = self._master()
            with self._db() as c:
                row = c.execute("SELECT wrapped FROM data_keys WHERE key_id = ?", (key_id,)).fetchone()
        if row is None:
            raise CannotDecrypt("no key for this run (deleted or expired)")
        return _open(master, row[0], f"data-key|{key_id}")

    def destroy(self, key_ids) -> None:
        """Crypto-shred these runs: their wrapped data keys are deleted (and
        zeroed in the key store file)."""
        ids = [(k,) for k in key_ids]
        if not ids:
            return
        with self._lock, self._db() as c:
            c.executemany("DELETE FROM data_keys WHERE key_id = ?", ids)

    def key_ids(self, *, older_than: float | None = None) -> set[str]:
        """Every key id; with `older_than` (seconds), only keys created at
        least that long ago."""
        with self._lock, self._db() as c:
            if older_than is None:
                return {r[0] for r in c.execute("SELECT key_id FROM data_keys")}
            return {r[0] for r in c.execute("SELECT key_id FROM data_keys WHERE created <= ?", (time.time() - older_than,))}

    def has_recent_keys(self, within: float) -> bool:
        """A key created in the last `within` seconds: a record may be in
        flight on another worker (its key written, its row not yet committed)."""
        with self._lock, self._db() as c:
            return c.execute("SELECT 1 FROM data_keys WHERE created > ? LIMIT 1", (time.time() - within,)).fetchone() is not None

    def rotate(self) -> None:
        """Destroy every data key and replace the master key with a new one.
        The old master file's bytes are overwritten before the new file is
        renamed over it."""
        with self._lock:
            with self._db() as c:
                c.execute("DELETE FROM data_keys")
            with self._db() as c:
                c.execute("VACUUM")
            tmp = self.path.with_name(f".{self.path.name}.new")
            tmp.unlink(missing_ok=True)
            self._write_new_master(tmp)
            try:
                size = self.path.stat().st_size
                with open(self.path, "r+b") as fh:
                    fh.write(b"\0" * size)
                    fh.flush()
                    os.fsync(fh.fileno())
            except OSError:
                pass
            os.replace(tmp, self.path)
            self._cached = None
        logger.info("run history: rotated its master key and destroyed every data key")

    # -- sealing -------------------------------------------------------------------

    @staticmethod
    def seal_with(dek: bytes, plain: bytes, aad: str) -> str:
        return PREFIX + base64.b64encode(_seal(dek, plain, aad)).decode()

    def open_for(self, key_id: str, token: str, aad: str) -> bytes:
        if not token.startswith(PREFIX):
            raise CannotDecrypt("not sealed")
        return _open(self.data_key(key_id), base64.b64decode(token[len(PREFIX) :]), aad)
