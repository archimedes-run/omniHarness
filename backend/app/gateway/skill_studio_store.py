"""What Skill Studio keeps beside a skill (006-G): its icon and colour, and the
test messages tried on it with what happened each time.

Kept OUT of the skill's own directory on purpose: nothing here is ever shown
to an agent (a skill's files are), and a skill's versioned writes (undo
restores a whole file set) never touch it. One JSON file per skill under the
gateway's home, written atomically. A deleted skill's record is kept, so undo
brings its tests back with it.

Test results are written ONLY by the test route, from what it observed (each
try's model call), never from a client's say-so.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

#: The icons a skill may show (the Studio's glyph grid).
SKILL_ICONS: tuple[str, ...] = (
    "list",
    "quote",
    "search",
    "code",
    "pen",
    "smile",
    "rocket",
    "chart",
    "target",
    "star",
    "calendar",
    "mail",
    "wand",
    "folder",
    "database",
    "terminal",
    "globe",
    "heart",
    "compass",
    "table",
    "layers",
    "mega",
    "shield",
    "book",
)
SKILL_COLORS = range(8)
#: Saved tests per skill, newest first; older ones drop off.
MAX_TESTS = 30
_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,127}$")
_LOCK = threading.Lock()


class SavedTry(BaseModel):
    loaded: bool
    other_skills: list[str] = Field(default_factory=list)
    error: str | None = None


class SavedTest(BaseModel):
    message: str
    at: str
    model: str
    listed: bool
    loaded: int
    total: int
    tries: list[SavedTry] = Field(default_factory=list)


class SkillStudioRecord(BaseModel):
    icon: str | None = None
    color: int | None = None
    tests: list[SavedTest] = Field(default_factory=list)


def _path(name: str) -> Path:
    from omniharness.config.paths import get_paths

    if not _NAME.fullmatch(name):
        raise ValueError(f"{name!r} is not a skill name")
    return get_paths().base_dir / "skill-studio" / f"{name}.json"


def read(name: str) -> SkillStudioRecord:
    path = _path(name)
    try:
        return SkillStudioRecord.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return SkillStudioRecord()


def _write(name: str, record: SkillStudioRecord) -> None:
    path = _path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{name}.")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(record.model_dump_json(indent=2))
    os.replace(tmp, path)


def set_appearance(name: str, icon: str | None, color: int | None) -> SkillStudioRecord:
    if icon is not None and icon not in SKILL_ICONS:
        raise ValueError(f"{icon!r} is not a skill icon")
    if color is not None and color not in SKILL_COLORS:
        raise ValueError(f"{color!r} is not a skill colour")
    with _LOCK:
        record = read(name)
        record.icon, record.color = icon, color
        _write(name, record)
        return record


def save_test(name: str, test: SavedTest) -> SkillStudioRecord:
    """Record one observed test (the same message replaces its older result)."""
    with _LOCK:
        record = read(name)
        record.tests = [test, *[t for t in record.tests if t.message != test.message]][:MAX_TESTS]
        _write(name, record)
        return record


def remove_test(name: str, message: str) -> SkillStudioRecord:
    with _LOCK:
        record = read(name)
        record.tests = [t for t in record.tests if t.message != message]
        _write(name, record)
        return record


def now() -> str:
    return datetime.now(UTC).isoformat()
