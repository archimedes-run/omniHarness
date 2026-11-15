"""Builds and checks of code artifacts in the chat's sandbox (Spec 012 Slice 2).

One seam, `sandbox_for(thread_id, owner_id)`: the thread's own hardened
container sandbox (the one coding jobs use), or None with a reason. Tests
replace it with a fake that plays the sandbox.

`check_version` runs the system checks on a stored version and records the
answer against the bytes it checked; `build_react` runs the pre-build. Both
are synchronous: the chat tools call them inside the tool call (so the
model reads the outcome in its result), the owner's routes from a
background task while the version's checks row or the build row says
"pending"/"running" with a heartbeat (a worker that dies leaves it stale,
read as not checked / interrupted).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable

from app.gateway.artifacts_store import checks, react_build
from app.gateway.artifacts_store.store import ArtifactStore, StoreError

logger = logging.getLogger(__name__)

NO_SANDBOX = "the checks need the chat's sandbox, which is not available here"


def _production_sandbox(thread_id: str, owner_id: str):
    from app.gateway.code_jobs import _hardened, production_sandbox_for

    if not _hardened():
        return None
    _, ops = production_sandbox_for(thread_id, owner_id)
    return ops


#: (thread_id, owner_id) -> sandbox ops or None. Tests replace it.
sandbox_factory: Callable[[str, str], object | None] = _production_sandbox


def sandbox_for(thread_id: str | None, owner_id: str):
    if not thread_id:
        return None
    try:
        return sandbox_factory(thread_id, owner_id)
    except Exception:  # noqa: BLE001 - no sandbox: the caller says so
        logger.info("artifact: no sandbox for thread %s", thread_id)
        return None


def _close(ops) -> None:
    close = getattr(ops, "close", None)
    if callable(close):
        try:
            close()
        except Exception:  # noqa: BLE001
            pass


def check_version(store: ArtifactStore, owner_id: str, artifact_id: str, n: int, thread_id: str | None) -> tuple[str, dict]:
    """Run the checks on version n and record them. Returns (state, result)."""
    try:
        summary, version, code, _check = store.code_version(owner_id, artifact_id, n)
    except StoreError:
        return "not_checked", checks.error("unreadable")
    if code.build_state != "ok":
        return "not_checked", checks.error("site_missing")
    from app.gateway.artifacts_store import frame

    try:
        stored = store.page_document(owner_id, artifact_id, n)
    except StoreError:
        return "not_checked", checks.error("site_missing")
    sha = code.frame_sha256 or ""
    ops = sandbox_for(thread_id, owner_id)
    if ops is None:
        result = {**checks.base(), "outcome": "error", "error": NO_SANDBOX, "error_code": "no_sandbox", "summary": [NO_SANDBOX]}
        store.set_check(owner_id, artifact_id, n, state="not_checked", result=result, frame_sha256=sha)
        return "not_checked", result
    try:
        result, shots = checks.run(ops, stored, beat=lambda: store.beat_check(owner_id, artifact_id, n))
    finally:
        _close(ops)
    result = checks.with_findings(result, frame.blocking(json.loads(code.findings or "[]")))
    state = checks.state_of(result)
    # Recorded against the bytes the checks loaded: the version's own.
    store.set_check(owner_id, artifact_id, n, state=state, result=result, frame_sha256=frame.frame_sha256(stored), shots=shots)
    return state, result


def build_react(owner_id: str, thread_id: str | None, source: dict, *, beat: Callable[[], None] | None = None) -> react_build.BuildResult | None:
    """The pre-build in the chat's sandbox; None when there is no sandbox."""
    ops = sandbox_for(thread_id, owner_id)
    if ops is None:
        return None
    try:
        return react_build.build(ops, source, beat=beat)
    finally:
        _close(ops)
