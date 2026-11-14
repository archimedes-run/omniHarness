"""Content-addressed blob storage (Spec 012 FR-036).

A blob lives at `{base_dir}/users/{user_id}/artifacts/blobs/sha256/{h[0:2]}/{h}`:
a path built from the owner id (validated by `Paths.user_dir`) and the hex
SHA-256 alone. Titles, ids and anything else a client or a model sends never
reach a path. A blob is written once (atomically) and never rewritten; it is
deleted only when no version of its owner references it (the repository
decides that).
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path

from omniharness.config.paths import get_paths

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class BadHash(ValueError):
    """Not 64 lowercase hex characters."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def root(owner_id: str) -> Path:
    return get_paths().user_dir(owner_id) / "artifacts" / "blobs" / "sha256"


def path_for(owner_id: str, content_hash: str) -> Path:
    if not isinstance(content_hash, str) or not _HEX64.fullmatch(content_hash):
        raise BadHash("not a content hash")
    base = root(owner_id)
    path = base / content_hash[:2] / content_hash
    # Belt and braces: the hash is hex, so this cannot leave the root.
    if base.resolve() not in path.resolve().parents:
        raise BadHash("outside the blob root")
    return path


def write(owner_id: str, data: bytes) -> str:
    """Store `data`; returns its hash. An existing blob is left as it is."""
    content_hash = sha256(data)
    path = path_for(owner_id, content_hash)
    if path.exists():
        return content_hash
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return content_hash


def read(owner_id: str, content_hash: str) -> bytes:
    return path_for(owner_id, content_hash).read_bytes()


def delete(owner_id: str, content_hash: str) -> None:
    path_for(owner_id, content_hash).unlink(missing_ok=True)
