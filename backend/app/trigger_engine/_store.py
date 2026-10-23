"""A small durable key-value map, atomically written.

Follows the pattern `app/channels/store.py` already uses for the same class of
data in the same process. Not SQLite: the data is tens of entries.
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class JsonStore:
    path: Path
    #: False: the FILE is authoritative. Every read re-reads it and every write
    #: is a read-modify-write under an exclusive lock on `<path>.lock`, so a
    #: change made by another worker (or process) is seen and never undone by
    #: a stale in-memory copy.
    cache: bool = True
    _data: dict = field(default_factory=dict)
    _loaded: bool = False

    @contextmanager
    def _write_lock(self):
        if self.cache:
            yield
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(f"{self.path}.lock", "a") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                self._loaded = False  # re-read under the lock
                yield
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)

    def load(self) -> dict:
        if self._loaded and self.cache:
            return self._data
        try:
            self._data = json.loads(self.path.read_text())
        except FileNotFoundError:
            self._data = {}
        except (json.JSONDecodeError, OSError) as exc:
            # A corrupt store must not take the engine down; start empty and say so.
            logger.error("store %s unreadable, starting empty: %s", self.path, exc)
            self._data = {}
        self._loaded = True
        return self._data

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as fh:
                json.dump(self._data, fh, indent=2, sort_keys=True)
            os.replace(tmp, self.path)  # atomic
        except Exception:
            Path(tmp).unlink(missing_ok=True)
            raise

    def get(self, key: str, default=None):
        return self.load().get(key, default)

    def set(self, key: str, value) -> None:
        with self._write_lock():
            self.load()[key] = value
            self.save()

    def delete(self, key: str) -> None:
        with self._write_lock():
            if self.load().pop(key, None) is not None:
                self.save()

    def keys(self) -> list[str]:
        return list(self.load())
