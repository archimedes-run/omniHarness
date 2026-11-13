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

  automations  one history per trigger rule id (Spec 010 FR-021) under the
           engine's state directory ({state_dir}/automation_versions/), snapshot
           = the rule as the rules file holds it (None: deleted). Materialised
           by app.gateway.automations_store into the rules file, which stays
           what the trigger engine reads; this module never writes that file.

  apps     one history per app id (Spec 011 FR-003) under the user's directory
           ({user}/app_versions/{app_id}.jsonl), snapshot {"manifest",
           "manifest_hash", "bundle_hash", "script_hashes"}. The bundle (one
           self-contained HTML document) is stored content-addressed beside it
           ({user}/app_bundles/{sha256}.html) and never rewritten: a version
           names its bundle by hash, so restore needs no copy.

A thing that existed before its first versioned write gets a baseline version
(source "existing") first, so the first edit can be undone too. For
automations the rules file can also be edited by hand at any time, so every
versioned write first records each rule whose current text differs from its
last version as a new baseline (FR-023): a hand edit is never lost, and never
silently undone.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import re
import shutil
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import yaml

from omniharness.config import agents_config
from omniharness.config.agents_config import SOUL_FILENAME, validate_agent_name

logger = logging.getLogger(__name__)

Kind = Literal["agent", "skill", "automation", "app"]
SOURCES = frozenset({"manual", "draft", "proposal", "chat", "undo", "existing", "code_job"})
LEAD_AGENT = "lead_agent"
CONFIG_FILENAME = "config.yaml"
#: The agent's standing grants (app/policy/grants.py). Changed ONLY by a write
#: that says so (`sets_autonomy=True`: the Autonomy tab's own Save). Every
#: other write, undo included, keeps the grants as they are now: undo restores
#: content, and never silently brings back (or drops) a grant.
AUTONOMY_KEY = "autonomy"
#: The agent's per-tool allowlist (006-G, AgentConfig.tools). An agent
#: changing ITSELF (source "proposal": the update_agent tool, between turns,
#: possibly steered by content it read) never changes it: only the owner's own
#: writes do (the agents API, undo). Content read in a run cannot widen, or
#: narrow, which tools the agent gets.
TOOLS_KEY = "tools"


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
    #: Automations only: which surface made the write ("page", "studio",
    #: "chat", "agent-deleted"; "hand-edit" for a baseline recorded because the
    #: rules file was edited by hand). Empty for agents and skills.
    via: str = ""

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
        Version(version=int(r["version"]), at=str(r.get("at") or r.get("ts") or ""), who=str(r.get("who", "")), source=str(r.get("source", "")), changed=list(r.get("changed") or []), snapshot=r.get("snapshot"), via=str(r.get("via") or ""))
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


def _keep_tools(snapshot: dict | None, before: dict | None) -> dict | None:
    """`snapshot` with the tool allowlist it had in `before` (none if none)."""
    if snapshot is None:
        return None
    config = dict(snapshot.get("config") or {})
    current = ((before or {}).get("config") or {}).get(TOOLS_KEY)
    if current is None:
        config.pop(TOOLS_KEY, None)
    else:
        config[TOOLS_KEY] = current
    return {**snapshot, "config": config}


def _without_autonomy(snapshot: dict | None) -> dict | None:
    """An unversioned agent's state with no grants. Grants come only from the
    Autonomy action, written to the store; an `autonomy` key in a config.yaml
    written outside it (a hand edit, a restored backup) is never adopted, or
    the first unrelated edit would make it live (review 5)."""
    if snapshot is None:
        return None
    config = dict(snapshot.get("config") or {})
    config.pop(AUTONOMY_KEY, None)
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
        before = versions[-1].snapshot if versions else _without_autonomy(_agent_on_disk(user_id, name))
        if not sets_autonomy:
            snapshot = _keep_autonomy(snapshot, before)
        if source == "proposal":
            snapshot = _keep_tools(snapshot, before)
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


def skill_owner(name: str, storage=None) -> str | None:
    """The account a custom skill belongs to: the owner_id its history first
    recorded (or the user of a "user:<id>" first write). None for a skill from
    before owners were stored, which only the owner account may reach
    (app.gateway.ownership)."""
    for record in _read_lines(_skill_storage(storage).get_skill_history_file(name)):
        if isinstance(record.get("owner_id"), str) and record["owner_id"]:
            return record["owner_id"]
        who = str(record.get("who") or "")
        if who.startswith("user:") and len(who) > 5:
            return who[5:]
    return None


def write_skill(
    name: str, changes: dict[str, str | None] | None, *, who: str, source: str, base_version: int | None = None, replace_all: bool = False, extra: dict[str, Any] | None = None, storage=None, owner_id: str | None = None
) -> Version:
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
        if after is not None:
            from omniharness.skills.validation import check_skill_limits, skill_dir_sizes

            # Refused before anything is written (SkillLimitError is a ValueError).
            # Measured over the WHOLE tree the write leaves on disk: every file
            # already there (dot-files and non-text files included, which the
            # versioned snapshot does not hold) plus this write's files.
            root = storage.get_custom_skill_dir(name)
            sizes = skill_dir_sizes(root) if root.exists() else {}
            if replace_all or changes is None:
                sizes = {p: n for p, n in sizes.items() if p not in (before or {"files": {}})["files"]}
            for path, text in (changes or {}).items():
                sizes.pop(path, None)
            sizes.update({path: len(text.encode("utf-8")) for path, text in after["files"].items()})
            check_skill_limits(name, sizes)
        changed = _changed((before or {}).get("files") if before else None, after["files"] if after else None)
        _materialise_skill(name, after, storage)
        record = {**(extra or {}), "version": current + 1, "at": now, "ts": now, "who": who, "source": source, "changed": changed, "snapshot": after}
        if owner_id:
            # Who the skill belongs to (the first one recorded counts).
            record["owner_id"] = owner_id
        _append(history, record)
        return Version(version=current + 1, at=now, who=who, source=source, changed=changed, snapshot=after)


def record_installed(name: str, *, who: str, storage=None, owner_id: str | None = None) -> Version | None:
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
        _append(history, {"version": version.version, "at": now, "ts": now, "who": who, "source": "manual", "action": "install", "changed": version.changed, "snapshot": on_disk, **({"owner_id": owner_id} if owner_id else {})})
        return version


# -- automations --------------------------------------------------------------
#
# The rules file holds every rule; the history is per rule id. One lock covers
# the whole file (a write replaces the file), taken by the materialiser
# (automations_store) around read, check, write and record, so two workers
# writing the same rule cannot both succeed.

AUTOMATION_VERSIONS_DIR = "automation_versions"


def automation_history_dir(state_dir: str | Path) -> Path:
    """Where automation histories live: the trigger engine's own state dir."""
    return Path(state_dir) / AUTOMATION_VERSIONS_DIR


def _automation_file(history_dir: Path, rule_id: str) -> Path:
    """A rule id is any non-empty string (the engine's parser), so the file name
    is a readable slug plus a hash of the exact id: two ids that differ only by
    case or punctuation never share a history, on any filesystem."""
    slug = re.sub(r"[^a-z0-9-]+", "-", rule_id.lower()).strip("-")[:60] or "rule"
    return history_dir / f"{slug}-{hashlib.sha256(rule_id.encode()).hexdigest()[:12]}.jsonl"


@contextmanager
def automations_locked(history_dir: Path) -> Iterator[None]:
    """The one lock for the rules file. Not re-entrant: take it once."""
    with _locked(history_dir / "rules.jsonl"):
        yield


def automation_history(history_dir: Path, rule_id: str) -> list[Version]:
    return _versions(_automation_file(history_dir, rule_id))


def automation_version(history_dir: Path, rule_id: str, on_file: dict | None) -> int:
    """The rule's current version, given the rule as the file holds it now.

    When the file matches the last version, that version. When it does not (a
    rule from before versioning, or a hand edit since), the number the next
    write will record it under as a baseline: reading never writes, and a
    writer that read this number is refused if anything changes before it saves.
    0: no such rule and no history."""
    versions = automation_history(history_dir, rule_id)
    if not versions:
        return 0 if on_file is None else 1
    last = versions[-1]
    return last.version if last.snapshot == on_file else last.version + 1


def _known_rule_ids(history_dir: Path) -> set[str]:
    out: set[str] = set()
    if history_dir.exists():
        for path in history_dir.glob("*.jsonl"):
            if path.name == "rules.jsonl":
                continue
            for record in _read_lines(path)[-1:]:
                if isinstance(record.get("rule_id"), str):
                    out.add(record["rule_id"])
    return out


def write_automations[R](
    history_dir: Path,
    before: dict[str, dict],
    after: dict[str, dict],
    *,
    who: str,
    source: str,
    materialise: Callable[[], R],
    base_versions: dict[str, int] | None = None,
    via: str = "",
) -> tuple[R, dict[str, Version]]:
    """Record a write to the rules file as per-rule versions.

    `before` / `after`: the file's rules by id, as read now and as the write
    leaves them. The caller holds `automations_locked`, has validated `after`,
    and passes `materialise`, which writes the file. Order:

      1. each `base_versions` entry is checked against the rule's current
         version (refused with StaleWriteError, nothing written);
      2. every rule whose text in the file differs from its last version (one
         from before versioning, a hand edit, a hand deletion) gets a baseline
         version, source "existing", so nothing on disk is ever lost;
      3. the file is written, then each rule the write changed gets its new
         version. A failed write records nothing.

    Returns what `materialise` returned and the new version of each changed rule."""
    if source not in SOURCES:
        raise ValueError(f"unknown version source {source!r}")
    for rule_id, base in (base_versions or {}).items():
        current = automation_version(history_dir, rule_id, before.get(rule_id))
        if base != current:
            raise StaleWriteError("automation", rule_id, base, current)
    now = datetime.now(UTC).isoformat()
    pending: list[tuple[Path, dict]] = []
    made: dict[str, Version] = {}
    for rule_id in sorted(set(before) | _known_rule_ids(history_dir)):
        on_file = before.get(rule_id)
        versions = automation_history(history_dir, rule_id)
        if versions and versions[-1].snapshot == on_file:
            continue
        if not versions and on_file is None:
            continue
        last = versions[-1] if versions else None
        record = {
            "rule_id": rule_id,
            "version": (last.version if last else 0) + 1,
            "at": now,
            "who": "unknown",
            "source": "existing",
            "via": "hand-edit" if last else "",
            "changed": _changed(last.snapshot, on_file) if last else [],
            "snapshot": on_file,
        }
        pending.append((_automation_file(history_dir, rule_id), record))
    baseline = {r["rule_id"]: r["version"] for _, r in pending}
    for rule_id in sorted(set(before) | set(after)):
        old, new = before.get(rule_id), after.get(rule_id)
        if old == new:
            continue
        current = baseline.get(rule_id) or automation_version(history_dir, rule_id, old)
        version = Version(version=current + 1, at=now, who=who, source=source, changed=_changed(old, new), snapshot=new, via=via)
        made[rule_id] = version
        pending.append((_automation_file(history_dir, rule_id), {"rule_id": rule_id, "version": version.version, "at": now, "who": who, "source": source, "via": via, "changed": version.changed, "snapshot": new}))
    result = materialise()
    for path, record in pending:
        _append(path, record)
    return result, made


def automation_target(history_dir: Path, rule_id: str, to_version: int) -> dict | None:
    """The rule as it was at `to_version`, for undo. Version 0 is "before it
    was created": only for a rule whose first version created it (undo of a
    create writes a deleted version, FR-020); a rule recorded from an existing
    file has no known state before that."""
    versions = automation_history(history_dir, rule_id)
    if to_version == 0 and versions and versions[0].source != "existing":
        return None
    target = next((v for v in versions if v.version == to_version), None)
    if target is None:
        raise VersionNotFoundError(f"automation '{rule_id}' has no version {to_version}")
    return target.snapshot


# -- apps ---------------------------------------------------------------------
#
# Spec 011. Only a verified app-mode coding job (source "code_job") or a
# library Restore (source "undo") writes here; the gateway's registration
# (app.gateway.apps.registry) is the one caller of write_app.

APP_VERSIONS_DIR = "app_versions"
APP_BUNDLES_DIR = "app_bundles"
_APP_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")
_BUNDLE_HASH = re.compile(r"^[0-9a-f]{64}$")


def validate_app_id(app_id: str) -> str:
    if not isinstance(app_id, str) or not _APP_ID.match(app_id):
        raise ValueError(f"invalid app id {app_id!r}")
    return app_id


def _app_root(user_id: str) -> Path:
    from omniharness.config.paths import get_paths

    return get_paths().user_dir(user_id)


def _app_history_file(user_id: str, app_id: str) -> Path:
    return _app_root(user_id) / APP_VERSIONS_DIR / f"{validate_app_id(app_id)}.jsonl"


def write_app_bundle(user_id: str, html: bytes) -> str:
    """Store one bundle content-addressed; returns its SHA-256. Idempotent: a
    bundle already stored is left as it is (same hash, same bytes)."""
    digest = hashlib.sha256(html).hexdigest()
    path = _app_root(user_id) / APP_BUNDLES_DIR / f"{digest}.html"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("wb", delete=False, dir=str(path.parent)) as handle:
            handle.write(html)
            tmp = Path(handle.name)
        tmp.replace(path)
    return digest


def read_app_bundle(user_id: str, digest: str) -> bytes:
    """The bundle with this hash, checked against it (a changed file is refused)."""
    if not _BUNDLE_HASH.match(str(digest or "")):
        raise VersionNotFoundError("invalid bundle hash")
    path = _app_root(user_id) / APP_BUNDLES_DIR / f"{digest}.html"
    if not path.exists():
        raise VersionNotFoundError(f"bundle {digest} is not stored")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        raise VersionNotFoundError(f"bundle {digest} does not match its hash")
    return data


def app_history(user_id: str, app_id: str) -> list[Version]:
    return _versions(_app_history_file(user_id, app_id))


def app_restored_from(user_id: str, app_id: str) -> dict[int, int]:
    """version -> the version it restored, for versions written by Restore."""
    return {int(r["version"]): int(r["restored_from"]) for r in _read_lines(_app_history_file(user_id, app_id)) if isinstance(r.get("version"), int) and isinstance(r.get("restored_from"), int)}


def app_ids(user_id: str) -> list[str]:
    directory = _app_root(user_id) / APP_VERSIONS_DIR
    if not directory.is_dir():
        return []
    return sorted(p.stem for p in directory.glob("*.jsonl") if _APP_ID.match(p.stem))


def write_app(user_id: str, app_id: str, snapshot: dict, *, who: str, source: str, base_version: int | None = None, restored_from: int | None = None) -> Version:
    """Record a new version of an app. The snapshot's bundle must already be
    stored (write_app_bundle). Refused (StaleWriteError) when `base_version`
    is given and is not the current version."""
    if source not in ("code_job", "undo"):
        raise ValueError("an app version is written only by a verified coding job or a Restore")
    if not isinstance(snapshot, dict) or not _BUNDLE_HASH.match(str(snapshot.get("bundle_hash", ""))):
        raise ValueError("an app snapshot names its bundle by hash")
    read_app_bundle(user_id, snapshot["bundle_hash"])  # stored and intact
    history = _app_history_file(user_id, app_id)
    with _locked(history):
        versions = _versions(history)
        current = versions[-1].version if versions else 0
        if base_version is not None and base_version != current:
            raise StaleWriteError("app", app_id, base_version, current)
        before = versions[-1].snapshot if versions else None
        changed = ["created"] if before is None else _changed(before, snapshot)
        if restored_from is not None:
            changed = [f"restored from version {restored_from}", *changed]
        now = datetime.now(UTC).isoformat()
        record = {"app_id": app_id, "version": current + 1, "at": now, "who": who, "source": source, "changed": changed, "snapshot": snapshot}
        if restored_from is not None:
            record["restored_from"] = restored_from
        _append(history, record)
        return Version(version=current + 1, at=now, who=who, source=source, changed=changed, snapshot=snapshot)


def restore_app(user_id: str, app_id: str, to_version: int, *, who: str, base_version: int | None = None) -> Version:
    """Restore `to_version` as a NEW version (undo is a new version, 010)."""
    target = next((v for v in app_history(user_id, app_id) if v.version == to_version), None)
    if target is None or target.snapshot is None:
        raise VersionNotFoundError(f"app '{app_id}' has no version {to_version}")
    return write_app(user_id, app_id, dict(target.snapshot), who=who, source="undo", base_version=base_version, restored_from=to_version)


# -- undo ---------------------------------------------------------------------


def undo(kind: Kind, name: str, to_version: int, *, who: str, base_version: int | None, user_id: str | None = None, storage=None) -> Version:
    """Restore `to_version` as a NEW version (the history only ever grows).

    For an agent this restores its CONTENT: its grants stay as they are now
    (write_agent keeps them); changing those is the Autonomy action's alone."""
    if kind == "automation":
        # The rules file is materialised by app.gateway.automations_store, which
        # this package cannot import: see app.gateway.routers.automations.undo_rule.
        raise ValueError("undo an automation through app.gateway.routers.automations.undo_rule")
    if kind == "app":
        return restore_app(user_id or "", name, to_version, who=who, base_version=base_version)
    versions = agent_history(user_id or "", name) if kind == "agent" else skill_history(name, storage)
    target = next((v for v in versions if v.version == to_version), None)
    if target is None:
        raise VersionNotFoundError(f"{kind} '{name}' has no version {to_version}")
    if kind == "agent":
        return write_agent(user_id or "", name, target.snapshot, who=who, source="undo", base_version=base_version)
    files = (target.snapshot or {}).get("files") if target.snapshot is not None else None
    return write_skill(name, files, who=who, source="undo", base_version=base_version, replace_all=True, storage=storage)
