"""Single-runner election (multi-worker safety).

WHY THIS EXISTS. The gateway runs under `uvicorn --workers N` — 4 by default in
docker/docker-compose.yaml. Every worker is a separate OS process with its own
memory, so without election every worker starts its own engine and the four
politeness mechanisms degrade independently:

  fingerprints   file-backed, but JsonStore caches on first load and never
                 re-reads, so each worker holds a permanently stale snapshot;
                 seen()->record() is also read-modify-write with no lock
  quiet hours    DeferralQueue.pending is an in-memory list, per process
  mid-exchange   InterruptQueue._queued is an in-memory list, per process
  coalescing     the window is per-runner, so three rules landing on three
                 workers coalesce into nothing and deliver three messages

That last one is the reason election beats "make each mechanism concurrent-safe":
coalescing does not fail loudly under concurrency, it silently becomes a no-op.
Four separate mechanisms is four chances to get that subtly wrong for a
single-user assistant.

WHY NOT `GATEWAY_WORKERS=1`. It is a setting nobody set on purpose and nobody
will remember. Election is correct at any worker count, including the one
someone raises later without thinking about triggers.

TWO BACKENDS, CHOSEN BY THE DATABASE BACKEND.

`PostgresAdvisoryLock` is the intended production shape: session-scoped
`pg_try_advisory_lock`, released by the server when the holding session drops,
and correct across hosts.

`FileLock` covers the configuration that actually ships today. The compose stack
defines no postgres service (nginx, frontend, gateway, provisioner,
omni-harness) and `DatabaseConfig.backend` defaults to "memory"; the reference
config uses "sqlite". A postgres-only lock would be unavailable in exactly the
deployment where the four workers live. `flock` has the property that matters
most here — the OS releases it when the holder dies, with no lease, heartbeat,
or timeout to tune — and uvicorn workers are always processes on one host, which
is precisely the scope of the problem.

Host scope is not the limiting factor for multi-host anyway: gateway internal
auth is a token generated per process at import, so the injection path is
already single-host by construction.
"""

from __future__ import annotations

import errno
import logging
import os
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)

#: Stable key for the trigger-engine leadership lock. Arbitrary but fixed: two
#: gateways sharing a database must contend for the same key.
ADVISORY_LOCK_KEY = 0x4F4D4E49  # ASCII "OMNI"


class SingleRunnerLock(Protocol):
    """Non-blocking, self-releasing leadership lock.

    `acquire()` MUST NOT block: a worker that loses the election continues
    serving requests without an engine. It is not degraded — three of four
    workers are meant to lose.
    """

    def acquire(self) -> bool: ...

    def release(self) -> None: ...

    @property
    def held(self) -> bool: ...


class FileLock:
    """`flock`-based lock. The OS releases it if the holder dies.

    No lease, no heartbeat, no expiry to tune — which removes the entire class
    of bug where a leader is declared dead while still running, or stays leader
    after dying.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._fd: int | None = None

    def acquire(self) -> bool:
        import fcntl

        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(fd)
            if exc.errno in (errno.EACCES, errno.EAGAIN):
                return False  # another worker holds it — the expected case
            raise
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode())
        self._fd = fd
        return True

    def release(self) -> None:
        if self._fd is None:
            return
        import fcntl

        try:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
        finally:
            os.close(self._fd)
            self._fd = None

    @property
    def held(self) -> bool:
        return self._fd is not None


class PostgresAdvisoryLock:
    """`pg_try_advisory_lock`, held for the life of a dedicated session.

    Session-scoped rather than transaction-scoped so the lock survives between
    engine cycles, and is released by the server when the connection drops —
    including when the holding process dies without cleanup.
    """

    def __init__(self, dsn: str, key: int = ADVISORY_LOCK_KEY) -> None:
        self.dsn = dsn
        self.key = key
        self._conn = None

    def acquire(self) -> bool:
        import psycopg

        conn = psycopg.connect(self.dsn, autocommit=True)
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_try_advisory_lock(%s)", (self.key,))
                row = cur.fetchone()
                got = bool(row and row[0])
        except Exception:
            conn.close()
            raise
        if not got:
            conn.close()
            return False
        self._conn = conn
        return True

    def release(self) -> None:
        if self._conn is None:
            return
        try:
            with self._conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(%s)", (self.key,))
        except Exception:
            logger.warning("advisory unlock failed; closing the session releases it anyway")
        finally:
            self._conn.close()
            self._conn = None

    @property
    def held(self) -> bool:
        return self._conn is not None


def build_lock(*, backend: str, postgres_url: str, lock_dir: Path) -> SingleRunnerLock:
    """Choose a lock implementation from the configured database backend.

    Postgres when the deployment has one; a file lock otherwise, because the
    default and reference configurations have no database server to contend on.
    """
    if backend == "postgres" and postgres_url:
        return PostgresAdvisoryLock(postgres_url)
    return FileLock(lock_dir / "trigger-engine.lock")
