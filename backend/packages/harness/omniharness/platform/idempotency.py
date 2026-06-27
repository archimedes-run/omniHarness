"""Idempotency-key helpers for platform workflow execution.

Contract (enforced starting Phase 1/2)
---------------------------------------
Before creating a run for a scheduled or event-triggered workflow,
compute its idempotency key.  If a run with that key already exists,
no-op instead of creating a duplicate.

Two canonical forms
-------------------
Scheduled runs:
    key = compute_idempotency_key(workflow_id, scheduled_time=<ISO-8601 str>)
    deterministic: same workflow + same scheduled slot → same key.

Event/trigger runs:
    key = compute_idempotency_key(workflow_id, trigger_payload=<dict>)
    deterministic: payload key order is normalised before hashing, so
    {"a": 1, "b": 2} and {"b": 2, "a": 1} produce the same key.

Neither form adds a column to any table yet (Phase 0).  The key is
intended to be stored in RunRow.idempotency_key (to be added in Phase 1).

Implementation notes
--------------------
- stable_hash() serialises a dict to JSON with sorted keys and no
  whitespace, then SHA-256s the UTF-8 bytes.  Nested dicts and lists
  are recursively sorted where possible.
- compute_idempotency_key() prefixes the hash with a human-readable
  namespace so keys are greppable in logs.
"""

from __future__ import annotations

import hashlib
import json


def stable_hash(payload: dict) -> str:
    """Return a hex SHA-256 of ``payload`` serialised with sorted keys.

    Sorting is applied recursively to nested dicts so that payloads
    differing only in key order hash identically.

    Args:
        payload: Arbitrary JSON-serialisable dict.

    Returns:
        64-char lowercase hex string.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_idempotency_key(
    workflow_id: str,
    *,
    scheduled_time: str | None = None,
    trigger_payload: dict | None = None,
) -> str:
    """Derive a deterministic idempotency key for a workflow execution.

    Exactly one of ``scheduled_time`` or ``trigger_payload`` must be
    provided.

    Args:
        workflow_id:      The workflow's stable ID.
        scheduled_time:   ISO-8601 string for the scheduled slot
                          (use ``datetime.isoformat()`` or equivalent).
        trigger_payload:  The trigger event payload dict.

    Returns:
        A namespaced key like ``"wf:<workflow_id>:sched:<hash>"`` or
        ``"wf:<workflow_id>:trig:<hash>"``.

    Raises:
        ValueError: If neither or both of the optional args are provided.
    """
    if scheduled_time is None and trigger_payload is None:
        raise ValueError("Provide exactly one of scheduled_time or trigger_payload")
    if scheduled_time is not None and trigger_payload is not None:
        raise ValueError("Provide exactly one of scheduled_time or trigger_payload")

    if scheduled_time is not None:
        raw = hashlib.sha256(f"{workflow_id}:{scheduled_time}".encode()).hexdigest()
        return f"wf:{workflow_id}:sched:{raw}"

    raw = stable_hash({"workflow_id": workflow_id, "payload": trigger_payload})
    return f"wf:{workflow_id}:trig:{raw}"
