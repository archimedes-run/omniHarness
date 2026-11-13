"""Edits to the trigger rule file, made safely (Phase 2.5, Automations).

Feature 004 had no rule editor on purpose (FR-036): a read surface must not
write. This is the one write path (write_rules, called only by the automations
router's edit_rules, which Studio's schedules and chat go through too), and it
keeps the guarantees the engine already gives a hand-edited file:

  * VALIDATE FIRST, with the engine's own parser and the same set of supported
    trigger types. An invalid edit never reaches the file, so the rules in
    force stay in force, and the reason comes back to be shown inline.
  * WRITE ATOMICALLY: a temporary file in the same directory, fsync, rename.
    The engine re-reads on a changed mtime, so it never sees half a file.
  * NEVER CLOBBER A HAND EDIT: every write names the version (a hash of the
    file's bytes) it was based on, and is refused if the file changed since.
  * EVERY WRITE IS A VERSION (Spec 010 FR-021): one history per rule in the
    versioned config store (config_versions, kind "automation"), with undo as
    a new version and stale rule versions refused. A rule edited by hand is
    recorded as a new baseline before the next write (FR-023).
  * KEEP EVERYTHING ELSE: quiet hours, comments and any other keys are left as
    they are; only the `rules` list changes.
  * REFUSE THE SHIPPED DEFAULTS: with no rules_path configured the engine runs
    the defaults inside the repo, which an edit must not modify in place.

The engine's existing hot reload (ConfigLoader.load on mtime) applies the change.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.trigger_engine.config import ConfigError, check_sources, parse
from omniharness.config import config_versions


class RulesEditError(Exception):
    """An edit was refused. `status` is the HTTP status the route returns."""

    def __init__(self, message: str, status: int) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class RulesFile:
    path: Path
    doc: dict
    version: str


def version_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def read_rules(path: Path) -> RulesFile:
    data = path.read_bytes()
    return RulesFile(path=path, doc=json.loads(data), version=version_of(data))


def validate(doc: dict, supported_types, before: dict | None = None) -> None:
    """The engine's own checks. Raises RulesEditError(422) with its message.

    A rule the engine would refuse on its own (config.RuleRefused: a bad
    `agent` or `show_on_home`) is refused here too, unless it is exactly as it
    already is in `before`: a hand-written rule the engine already reports as
    not loaded must not block every other edit to the file."""
    try:
        cfg = parse(doc)
        check_sources(cfg, supported_types)
    except ConfigError as exc:
        raise RulesEditError(str(exc), 422) from exc
    if cfg.refused:
        unchanged = {r.get("id"): r for r in (before or {}).get("rules") or [] if isinstance(r, dict)}
        for refused in cfg.refused:
            mine = next((r for r in doc.get("rules") or [] if isinstance(r, dict) and str(r.get("id")) == refused.id), None)
            if mine is None or unchanged.get(mine.get("id")) != mine:
                raise RulesEditError(refused.error, 422)


def rules_by_id(doc: dict | None) -> dict[str, dict]:
    """The document's rules keyed by id (entries that are not rules are left
    out: the engine's parser refuses a file holding them anyway)."""
    return {r["id"]: r for r in (doc or {}).get("rules") or [] if isinstance(r, dict) and isinstance(r.get("id"), str)}


def history_dir(trigger_cfg) -> Path:
    """Where the per-rule histories live (config_versions kind "automation")."""
    return config_versions.automation_history_dir(getattr(trigger_cfg, "state_dir", None) or ".omni-harness/triggers")


def _replace_file(path: Path, doc: dict) -> str:
    """Atomically replace the rules file with `doc`. Called ONLY as the
    versioned store's materialiser in write_rules (the config-writes gate
    test checks that)."""
    data = (json.dumps(doc, indent=2, ensure_ascii=False) + "\n").encode()
    mode = path.stat().st_mode & 0o777
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        os.fchmod(fd, mode)  # keep the file's permissions; mkstemp makes it 0600
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return version_of(data)


def write_rules(
    path: Path,
    change: Callable[[dict], dict],
    *,
    expected_version: str | None,
    supported_types,
    writable: bool,
    history: Path,
    who: str,
    source: str = "manual",
    via: str = "",
    base_versions: dict[str, int] | None = None,
) -> str:
    """THE write to the rules file (Spec 010 FR-021). Under the store's lock:
    read the file, refuse a stale file version (`expected_version`, the hash
    the caller read; None: the file as it is now), apply `change`, validate
    with the engine's parser, then hand the write to the versioned store
    (config_versions.write_automations), which refuses a stale rule version
    (`base_versions`), records baselines for anything edited by hand, writes
    the file through `_replace_file`, and records a version per changed rule.
    Returns the file's new version (hash)."""
    if not writable:
        raise RulesEditError("No rules file is configured, so the engine is running the shipped defaults, which are not edited in place. Set trigger_engine.rules_path in config.yaml to a file of your own (copy the defaults to start).", 409)
    with config_versions.automations_locked(history):
        data = path.read_bytes()
        if expected_version is not None and version_of(data) != expected_version:
            raise RulesEditError("The rules file changed since this page loaded it (edited elsewhere?). Reload to see the current rules, then make the change again.", 409)
        current = json.loads(data)
        if not isinstance(current, dict):
            raise RulesEditError("The rules file is not a JSON object; fix it by hand first.", 500)
        doc = change(current)
        validate(doc, supported_types, current)
        try:
            new_version, _ = config_versions.write_automations(history, rules_by_id(current), rules_by_id(doc), who=who, source=source, via=via, base_versions=base_versions, materialise=lambda: _replace_file(path, doc))
        except config_versions.StaleWriteError as exc:
            raise RulesEditError(str(exc), 409) from exc
        return new_version


def put_rule(doc: dict, rule_id: str, rule: dict | None) -> dict:
    """`doc` with the rule `rule_id` set to `rule` wherever it is (appended if
    absent), or removed (None). For undo, which may bring back a deleted rule."""
    rules = [r for r in doc.get("rules") or []]
    ids = [r.get("id") if isinstance(r, dict) else None for r in rules]
    if rule is None:
        return {**doc, "rules": [r for r, i in zip(rules, ids) if i != rule_id]}
    if rule_id in ids:
        rules[ids.index(rule_id)] = rule
    else:
        rules.append(rule)
    return {**doc, "rules": rules}


def with_rule(doc: dict, rule: dict, *, replace: str | None) -> dict:
    """A copy of `doc` with `rule` added (replace=None) or put in place of the
    rule whose id is `replace`. Other keys are untouched."""
    rules = list(doc.get("rules") or [])
    ids = [r.get("id") for r in rules]
    if replace is None:
        if rule.get("id") in ids:
            raise RulesEditError(f"A rule with id {rule.get('id')!r} already exists.", 409)
        rules.append(rule)
    else:
        if replace not in ids:
            raise RulesEditError(f"No rule with id {replace!r}.", 404)
        rules[ids.index(replace)] = rule
    return {**doc, "rules": rules}


def without_rule(doc: dict, rule_id: str) -> dict:
    rules = list(doc.get("rules") or [])
    if rule_id not in [r.get("id") for r in rules]:
        raise RulesEditError(f"No rule with id {rule_id!r}.", 404)
    return {**doc, "rules": [r for r in rules if r.get("id") != rule_id]}


#: Starting points for a new automation. Each is a valid rule as written; the
#: form fills in the id and lets every field be changed before saving.
TEMPLATES: list[dict] = [
    {
        "template": "morning-brief",
        "title": "Morning brief",
        "description": "A short briefing on what is waiting, each weekday morning.",
        "rule": {
            "id": "morning-brief",
            "name": "Morning brief",
            "type": "cron",
            "enabled": True,
            "match": {"schedule": "45 8 * * 1-5", "timezone": "America/New_York"},
            "prompt": "Good morning. Brief me on what is waiting, as of {scheduled_at}.",
            "destination": "auto",
        },
    },
    {
        "template": "blocked-session",
        "title": "Blocked coding session",
        "description": "Tell me when a Claude Code session is waiting on me.",
        "rule": {
            "id": "blocked-session",
            "name": "Blocked session alert",
            "type": "watcher",
            "enabled": True,
            "match": {"event": "waiting-on-user"},
            "prompt": "The session in {project} is waiting on you: {last_message}",
            "destination": "auto",
        },
    },
    {
        "template": "weekly-review",
        "title": "Weekly review",
        "description": "Every Friday afternoon: what got done this week and what is still open.",
        "rule": {
            "id": "weekly-review",
            "name": "Weekly review",
            "type": "cron",
            "enabled": True,
            "match": {"schedule": "0 16 * * 5", "timezone": "America/New_York"},
            "prompt": "It is {scheduled_at}. Review my week: what got done, what is still open, and what I should pick up first on Monday.",
            "destination": "auto",
        },
    },
]
