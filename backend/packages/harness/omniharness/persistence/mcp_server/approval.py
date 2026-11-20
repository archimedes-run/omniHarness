"""Approval bound to the code it approves.

Pure functions over a server row (as ``McpServerRepository`` returns it). The
one question: is the code stored right now the code the owner approved? It is
derived on every read from the stored hash and the stored source, so a change
to the code cannot stay approved through a missed update.

The record (hash, who, when) is the server's own; a later step may grant it
without the owner (for example for a read-only server) by writing the same
record with a different ``approved_by``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any


def code_sha256(source: str | None) -> str | None:
    """SHA-256 of the exact UTF-8 bytes of the server's code (None: no code)."""
    if not source:
        return None
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def matches_code(sha256: str | None, source: str | None) -> bool:
    """True when ``sha256`` is the hash of ``source`` (never for no code)."""
    current = code_sha256(source)
    return current is not None and bool(sha256) and sha256 == current


def current_code_approved(row: Mapping[str, Any]) -> bool:
    """True only when an approval exists for exactly the stored code."""
    return matches_code(row.get("approved_code_sha256"), row.get("source_code"))


def deployed_code_is_current(row: Mapping[str, Any]) -> bool:
    """True only when the running container was built from the stored code."""
    return matches_code(row.get("deployed_code_sha256"), row.get("source_code"))
