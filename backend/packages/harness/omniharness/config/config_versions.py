"""One versioned store for every agent and skill config write (Feature 006, user decision 2026-10-20).

EVERY change to an agent or a skill goes through here: creating, editing,
saving a draft, an agent updating itself, granting or revoking autonomy,
deleting. Grants change only through a write that says so (AUTONOMY_KEY). Each write is a new VERSION: who made it, when, what changed, and its
source (manual, draft, proposal, chat, undo). Undo restores an earlier version
AS A NEW VERSION, so nothing is ever rewritten in place. A write that names the
version it was based on is refused when that is no longer the current one: two
tabs, or a person and the agent, cannot silently overwrite each other.

tests/gates/test_config_writes_go_through_versions.py fails if anything else
writes an agent's config.yaml or SOUL.md or a custom skill's files.

LAYOUT. A version records the WHOLE state after the write (a snapshot), so any
version can be restored without replaying a chain:

  agents   {user}/agent_versions/{name}.jsonl, snapshot {"config", "soul"}
           (config None: deleted). Materialised to the agent's config.yaml and
           SOUL.md, which is what the runtime reads.
  lead     the lead agent is the entity "lead_agent": its autonomy lives in
           {user}/lead_agent/config.yaml, its SOUL.md at the base directory.
  skills   the skill's own history file (custom/.history/{name}.jsonl, the one
           skill_manage and the rollback route already use), snapshot
           {"files": {path: text}} (None: deleted). Lines without a "version"
           are older history and are kept, not numbered.

A thing that existed before its first versioned write gets a baseline version
(source "existing") first, so the first edit can be undone too.
"""

from __future__ import annotations

import fcntl
import json
import logging
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import yaml

from omniharness.config import agents_config
from omniharness.config.agents_config import SOUL_FILENAME, validate_agent_name

logger = logging.getLogger(__name__)

Kind = Literal["agent", "skill"]
SOURCES = frozenset({"manual", "draft", "proposal", "chat", "undo", "existing"})
LEAD_AGENT = "lead_agent"
CONFIG_FILENAME = "config.yaml"
#: The agent's standing grants (app/policy/grants.py). Changed ONLY by a write
#: that says so (`sets_autonomy=True`: the Autonomy tab's own Save). Every
#: other write, undo included, keeps the grants as they are now: undo restores
#: content, and never silently brings back (or drops) a grant.
AUTONOMY_KEY = "autonomy"


class StaleWriteError(Exception):
    """The write was based on a version that is no longer the current one."""

    def __init__(self, kind: Kind, name: str, base: int, current: int):
        super().__init__(f"{kind} '{name}' changed since you opened it (you had version {base}, it is now version {current}). Reload to see the change, then try again.")
        self.base, self.current = base, current


class VersionNotFoundError(LookupError):
    pass


@dataclass(frozen=True)
class Version:
    version: int
    at: str
    who: str
    source: str
    changed: list[str]
    snapshot: dict | None

    def summary(self) -> dict:
        return {"version": self.version, "at": self.at, "who": self.who, "source": self.source, "changed": self.changed, "deleted": self.snapshot is None}


# -- persistence --------------------------------------------------------------


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=str(path.parent)) as handle:
        handle.write(text)
        tmp = Path(handle.name)
    tmp.replace(path)


@contextmanager
def _locked(history: Path) -> Iterator[None]:
    """One writer per thing at a time, across workers."""
    history.parent.mkdir(parents=True, exist_ok=True)
    with open(history.with_suffix(".lock"), "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _read_lines(history: Path) -> list[dict]:
    if not history.exists():
        return []
    out = []
    for line in history.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                logger.warning("skipping an unreadable line in %s", history)
    return out


def _versions(history: Path) -> list[Version]:
    return [
        Version(version=int(r["version"]), at=str(r.get("at") or r.get("ts") or ""), who=str(r.get("who", "")), source=str(r.get("source", "")), changed=list(r.get("changed") or []), snapshot=r.get("snapshot"))
        for r in _read_lines(history)
        if isinstance(r.get("version"), int)
    ]


def _append(history: Path, record: dict) -> None:
    history.parent.mkdir(parents=True, exist_ok=True)
    with history.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _changed(before: dict | None, after: dict | None) -> list[str]:
    if before is None and after is None:
        return []
    if before is None:
        return ["created"]
    if after is None:
        return ["deleted"]
    keys = sorted(set(before) | set(after))
    out = []
    for key in keys:
        b, a = before.get(key), after.get(key)
        if isinstance(b, dict) or isinstance(a, dict):
            out += [f"{key}.{k}" for k in sorted(set(b or {}) | set(a or {})) if (b or {}).get(k) != (a or {}).get(k)]
        elif b != a:
            out.append(key)
    return out


# -- agents -------------------------------------------------------------------


def _agent_paths(user_id: str, name: str) -> tuple[Path, Path, Path]:
    """(history, config.yaml, SOUL.md) for an agent of this user."""
    # The same resolution agents_config reads agents with.
    paths = agents_config.get_paths()
    root = paths.user_agents_dir(user_id).parent
    history = root / "agent_versions" / f"{name}.jsonl"
    if name == LEAD_AGENT:
        return history, root / LEAD_AGENT / CONFIG_FILENAME, paths.base_dir / SOUL_FILENAME
    agent_dir = paths.user_agent_dir(user_id, name)
    return history, agent_dir / CONFIG_FILENAME, agent_dir / SOUL_FILENAME


def _agent_on_disk(user_id: str, name: str) -> dict | None:
    _, config_file, soul_file = _agent_paths(user_id, name)
    if name != LEAD_AGENT and not config_file.exists():
        return None
    config = (yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}) if config_file.exists() else {}
    soul = soul_file.read_text(encoding="utf-8") if soul_file.exists() else ""
    return {"config": config, "soul": soul}


def _stage(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=str(path.parent), suffix=".tmp")
    try:
        handle.write(text)
        handle.close()
        return Path(handle.name)
    except BaseException:
        handle.close()
        Path(handle.name).unlink(missing_ok=True)
        raise


def _materialise_agent(user_id: str, name: str, snapshot: dict | None) -> None:
    """Both files or neither: every file is staged before any is replaced, and
    a failure part-way puts back what was replaced (the version is then not
    recorded, so the record never claims a state the disk does not hold)."""
    _, config_file, soul_file = _agent_paths(user_id, name)
    if snapshot is None:
        if name != LEAD_AGENT and config_file.parent.exists():
            shutil.rmtree(config_file.parent)
        return
    targets = [
        (config_file, yaml.dump(snapshot.get("config") or {}, default_flow_style=False, allow_unicode=True, sort_keys=False)),
        (soul_file, snapshot.get("soul") or ""),
    ]
    previous = {path: (path.read_text(encoding="utf-8") if path.exists() else None) for path, _ in targets}
    new_dir = name != LEAD_AGENT and not config_file.parent.exists()
    staged: list[tuple[Path, Path]] = []
    try:
        for path, text in targets:
            staged.append((_stage(path, text), path))
    except BaseException:
        for tmp, _ in staged:
            tmp.unlink(missing_ok=True)
        if new_dir and config_file.parent.exists():
            shutil.rmtree(config_file.parent)
        raise
    committed: list[Path] = []
    try:
        for tmp, path in staged:
            tmp.replace(path)
            committed.append(path)
    except BaseException:
        for tmp, _ in staged:
            tmp.unlink(missing_ok=True)
        for path in committed:
            before = previous[path]
            if before is None:
                path.unlink(missing_ok=True)
            else:
                path.write_text(before, encoding="utf-8")
        if new_dir and config_file.parent.exists():
            shutil.rmtree(config_file.parent)
        raise


def _normalise_agent_name(name: str) -> str:
    if name == LEAD_AGENT:
        return name
    return validate_agent_name(name.lower()) or ""


def agent_version(user_id: str, name: str) -> int:
    """The current version; 0 when no versioned write has happened yet."""
    name = _normalise_agent_name(name)
    versions = _versions(_agent_paths(user_id, name)[0])
    return versions[-1].version if versions else 0


def agent_history(user_id: str, name: str) -> list[Version]:
    return _versions(_agent_paths(user_id, _normalise_agent_name(name))[0])


def _keep_autonomy(snapshot: dict | None, before: dict | None) -> dict | None:
    """`snapshot` with the grants it had in `before` (none, if it had none)."""
    if snapshot is None:
        return None
    config = dict(snapshot.get("config") or {})
    current = ((before or {}).get("config") or {}).get(AUTONOMY_KEY)
    if current is None:
        config.pop(AUTONOMY_KEY, None)
    else:
        config[AUTONOMY_KEY] = current
    return {**snapshot, "config": config}


def write_agent(user_id: str, name: str, snapshot: dict | None, *, who: str, source: str, base_version: int | None = None, sets_autonomy: bool = False) -> Version:
    """Make `snapshot` ({"config": {...}, "soul": "..."}, or None to delete) the
    agent's new version. `base_version`: the version the change was made from;
    a write based on an older one is refused (None: the caller holds no view,
    as an agent updating itself between turns). Unless `sets_autonomy`, the
    agent's grants stay exactly as they are now, whatever `snapshot` says."""
    if source not in SOURCES:
        raise ValueError(f"unknown version source {source!r}")
    name = _normalise_agent_name(name)
    history = _agent_paths(user_id, name)[0]
    with _locked(history):
        versions = _versions(history)
        current = versions[-1].version if versions else 0
        if base_version is not None and base_version != current:
            raise StaleWriteError("agent", name, base_version, current)
        before = versions[-1].snapshot if versions else _agent_on_disk(user_id, name)
        if not sets_autonomy:
            snapshot = _keep_autonomy(snapshot, before)
        now = datetime.now(UTC).isoformat()
        if not versions and before is not None:
            # The state before versioning began, so the first edit can be undone.
            current = 1
            _append(history, {"version": 1, "at": now, "who": "unknown", "source": "existing", "changed": [], "snapshot": before})
        version = Version(version=current + 1, at=now, who=who, source=source, changed=_changed(before, snapshot), snapshot=snapshot)
        _materialise_agent(user_id, name, snapshot)
        _append(history, {"version": version.version, "at": now, "who": who, "source": source, "changed": version.changed, "snapshot": snapshot})
        return version


def current_agent_snapshot(user_id: str, name: str) -> dict | None:
    return current_agent_state(user_id, name)[0]


def current_agent_state(user_id: str, name: str) -> tuple[dict | None, int]:
    """(snapshot, version) read TOGETHER, so a writer can name the version it
    read as its base_version and be refused if anything changed since."""
    name = _normalise_agent_name(name)
    versions = _versions(_agent_paths(user_id, name)[0])
    if versions:
        return versions[-1].snapshot, versions[-1].version
    return _agent_on_disk(user_id, name), 0


# -- skills -------------------------------------------------------------------


def _skill_storage(storage=None):
    if storage is not None:
        return storage
    from omniharness.skills.storage import get_or_new_skill_storage

    return get_or_new_skill_storage()


def _skill_on_disk(name: str, storage=None) -> dict | None:
    storage = _skill_storage(storage)
    root = storage.get_custom_skill_dir(name)
    if not root.exists():
        return None
    files = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if path.is_file() and not any(part.startswith(".") for part in rel.parts):
            try:
                files[str(rel)] = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                logger.warning("skill %s: %s is not text and is not versioned", name, rel)
    return {"files": files}


def _materialise_skill(name: str, snapshot: dict | None, storage=None) -> None:
    storage = _skill_storage(storage)
    root = storage.get_custom_skill_dir(name)
    if snapshot is None:
        if root.exists():
            storage.delete_custom_skill(name)
        return
    wanted = snapshot.get("files") or {}
    for path, text in wanted.items():
        storage.write_custom_skill(name, path, text)
    current = _skill_on_disk(name, storage) or {"files": {}}
    for path in set(current["files"]) - set(wanted):
        (root / path).unlink(missing_ok=True)


def skill_version(name: str, storage=None) -> int:
    versions = _versions(_skill_storage(storage).get_skill_history_file(name))
    return versions[-1].version if versions else 0


def skill_history(name: str, storage=None) -> list[Version]:
    return _versions(_skill_storage(storage).get_skill_history_file(name))


def write_skill(name: str, changes: dict[str, str | None] | None, *, who: str, source: str, base_version: int | None = None, replace_all: bool = False, extra: dict[str, Any] | None = None, storage=None) -> Version:
    """Apply `changes` ({path: text, or None to remove}) to a custom skill as a
    new version; `changes` None deletes the skill. `replace_all` makes the
    files exactly `changes` (undo). `extra` keeps the older history fields
    (action, prev_content, ...) that the rollback route reads."""
    if source not in SOURCES:
        raise ValueError(f"unknown version source {source!r}")
    storage = _skill_storage(storage)
    name = storage.validate_skill_name(name)
    history = storage.get_skill_history_file(name)
    with _locked(history):
        versions = _versions(history)
        current = versions[-1].version if versions else 0
        if base_version is not None and base_version != current:
            raise StaleWriteError("skill", name, base_version, current)
        before = _skill_on_disk(name, storage)
        now = datetime.now(UTC).isoformat()
        if not versions and before is not None:
            current = 1
            _append(history, {"version": 1, "at": now, "ts": now, "who": "unknown", "source": "existing", "changed": [], "snapshot": before})
        if changes is None:
            after = None
        elif replace_all:
            after = {"files": {p: t for p, t in changes.items() if t is not None}}
        else:
            files = dict((before or {"files": {}})["files"])
            for path, text in changes.items():
                if text is None:
                    files.pop(path, None)
                else:
                    files[path] = text
            after = {"files": files}
        changed = _changed((before or {}).get("files") if before else None, after["files"] if after else None)
        _materialise_skill(name, after, storage)
        record = {**(extra or {}), "version": current + 1, "at": now, "ts": now, "who": who, "source": source, "changed": changed, "snapshot": after}
        _append(history, record)
        return Version(version=current + 1, at=now, who=who, source=source, changed=changed, snapshot=after)


def record_installed(name: str, *, who: str, storage=None) -> Version | None:
    """A skill unpacked from an archive by the installer (which has its own
    path checks): its files are recorded as the next version, so it appears in
    history and can be undone. None when it is not a custom skill on disk."""
    storage = _skill_storage(storage)
    name = storage.validate_skill_name(name)
    on_disk = _skill_on_disk(name, storage)
    if on_disk is None:
        return None
    history = storage.get_skill_history_file(name)
    with _locked(history):
        versions = _versions(history)
        before = versions[-1].snapshot if versions else None
        now = datetime.now(UTC).isoformat()
        version = Version(version=(versions[-1].version if versions else 0) + 1, at=now, who=who, source="manual", changed=["installed", *_changed((before or {}).get("files") if before else None, on_disk["files"])], snapshot=on_disk)
        _append(history, {"version": version.version, "at": now, "ts": now, "who": who, "source": "manual", "action": "install", "changed": version.changed, "snapshot": on_disk})
        return version


# -- undo ---------------------------------------------------------------------


def undo(kind: Kind, name: str, to_version: int, *, who: str, base_version: int | None, user_id: str | None = None, storage=None) -> Version:
    """Restore `to_version` as a NEW version (the history only ever grows).

    For an agent this restores its CONTENT: its grants stay as they are now
    (write_agent keeps them); changing those is the Autonomy action's alone."""
    versions = agent_history(user_id or "", name) if kind == "agent" else skill_history(name, storage)
    target = next((v for v in versions if v.version == to_version), None)
    if target is None:
        raise VersionNotFoundError(f"{kind} '{name}' has no version {to_version}")
    if kind == "agent":
        return write_agent(user_id or "", name, target.snapshot, who=who, source="undo", base_version=base_version)
    files = (target.snapshot or {}).get("files") if target.snapshot is not None else None
    return write_skill(name, files, who=who, source="undo", base_version=base_version, replace_all=True, storage=storage)
