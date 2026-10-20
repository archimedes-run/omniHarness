"""Approval bound to a code hash (Feature 006, #59).

Pure functions over a server row (as ``McpServerRepository`` returns it). The
one question they answer: is the code stored right now the code the user
approved, with the outbound hosts they saw? That is derived on every read and
never stored, so a code change can't stay approved by a missed update.
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


def current_code_approved(row: Mapping[str, Any]) -> bool:
    """True only when the stored code and hosts are exactly what was approved."""
    approval = row.get("approval") or None
    current = code_sha256(row.get("source_code"))
    if not approval or current is None:
        return False
    return approval.get("code_sha256") == current and row.get("approved_code_sha256") == current and list(approval.get("egress_hosts") or []) == list(row.get("egress_hosts") or [])
