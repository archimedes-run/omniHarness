"""Builder drafts: thread-scoped, never in the config store (Spec 010 FR-010, FR-004).

One small JSON file per chat, beside the chat's own data
(`{base}/users/{owner}/threads/{thread}/builder.json`, outside the folders a
sandbox mounts), deleted with the chat. It holds:

- `active`: the build this chat is in ("Building: <name>"), or null. At most
  one per chat. Set when the assistant calls builder_draft (FR-002: a builder
  tool call starts builder mode, never keywords); cleared by the chip's x.
- `drafts`: each draft, IMMUTABLE once written, under its own id. A revision
  is a new draft with a new id, so a card always saves exactly the draft it
  showed, and a card for an older draft can never save a newer one.

Dropping a build writes only this file: nothing in the config store changes.
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FILENAME = "builder.json"
#: Drafts kept per chat (the active one always kept).
KEEP_DRAFTS = 30


def _path(user_id: str, thread_id: str) -> Path:
    from omniharness.config.paths import get_paths

    return get_paths().thread_dir(thread_id, user_id=user_id) / FILENAME


@contextmanager
def _locked(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.with_suffix(".lock"), "a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _read(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"active": None, "drafts": {}}
    if not isinstance(data, dict):
        return {"active": None, "drafts": {}}
    data.setdefault("active", None)
    if not isinstance(data.get("drafts"), dict):
        data["drafts"] = {}
    return data


def _write(path: Path, data: dict[str, Any]) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".builder-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def new_draft_id() -> str:
    return f"d-{uuid.uuid4().hex[:12]}"


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def load(user_id: str, thread_id: str) -> dict[str, Any]:
    """The chat's builder state ({"active": ..., "drafts": {...}}). Reads only."""
    return _read(_path(user_id, thread_id))


def get_draft(user_id: str, thread_id: str, draft_id: str) -> dict[str, Any] | None:
    draft = load(user_id, thread_id)["drafts"].get(str(draft_id))
    return draft if isinstance(draft, dict) else None


def active(user_id: str, thread_id: str) -> dict[str, Any] | None:
    current = load(user_id, thread_id).get("active")
    return current if isinstance(current, dict) else None


def put_draft(user_id: str, thread_id: str, draft: dict[str, Any]) -> None:
    """Record a new draft and make it the chat's active build."""
    path = _path(user_id, thread_id)
    with _locked(path):
        data = _read(path)
        data["drafts"][draft["id"]] = draft
        data["active"] = {
            "draft_id": draft["id"],
            "kind": draft["kind"],
            "name": draft["name"],
            "title": draft.get("title") or draft["name"],
            "saved_version": None,
            "started_at": (data.get("active") or {}).get("started_at") if _same_target(data.get("active"), draft) else now(),
        }
        if len(data["drafts"]) > KEEP_DRAFTS:
            ordered = sorted(data["drafts"].values(), key=lambda d: str(d.get("created_at") or ""))
            for old in ordered[: len(data["drafts"]) - KEEP_DRAFTS]:
                if old["id"] != draft["id"]:
                    data["drafts"].pop(old["id"], None)
        _write(path, data)


def _same_target(current: Any, draft: dict[str, Any]) -> bool:
    return isinstance(current, dict) and current.get("kind") == draft.get("kind") and current.get("name") == draft.get("name")


def mark_saved(user_id: str, thread_id: str, draft_id: str, version: int) -> None:
    """The active build was saved (its chip stays until x or a new build)."""
    path = _path(user_id, thread_id)
    with _locked(path):
        data = _read(path)
        draft = data["drafts"].get(draft_id)
        if isinstance(draft, dict):
            draft["saved_version"] = version
        current = data.get("active")
        if isinstance(current, dict) and current.get("draft_id") == draft_id:
            current["saved_version"] = version
        _write(path, data)


def drop(user_id: str, thread_id: str) -> dict[str, Any] | None:
    """Leave builder mode: the active build is dropped (nothing saved). Returns
    what was active, or None. Writes only this chat's builder file."""
    path = _path(user_id, thread_id)
    if not path.exists():
        return None
    with _locked(path):
        data = _read(path)
        was = data.get("active")
        if not isinstance(was, dict):
            return None
        data["active"] = None
        draft = data["drafts"].get(was.get("draft_id"))
        if isinstance(draft, dict):
            draft["dropped"] = True
        _write(path, data)
        return was
