"""T054 — Gate 4: nothing is defined and never referenced by production code.

Five defects of this shape have been found in this project:

  KNOWN_INERT_TYPES defined, never wired            (a module-level CONSTANT)
  start_background_refresh never called by main()   (a function)
  Discovery.release() called only from a test       (a method)
  registry.merge() never called; server.py used replace_all()
  PINNED_LOCAL_SOURCES with zero consumers          (another constant)

Every one passed its unit tests. Unit tests structurally cannot catch this: a
unit test constructs the thing it tests, so "is anything calling this?" is
always true from inside the test.

WHY A TARGETED CHECK RATHER THAN `vulture`. Vulture was tried first, because
covering constants as well as functions is exactly what a plain caller-check
misses. It scores unused functions and classes at confidence 60, so it must run
at 60 to see them — and at 60 it reports 30 findings on a clean tree, most of
them dataclass fields it cannot model. A thirty-entry whitelist of false
positives is precisely how a gate dies: the entries stop being read, and a real
finding hides among them. This check knows what a dataclass field is, so it has
no such noise, and it covers constants, which is the gap that sent us to vulture
in the first place.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[2] / "app" / "trigger_engine"
WHITELIST = MODULE / ".wiring-whitelist"


TASKS = Path(__file__).resolve().parents[3] / "specs" / "002-trigger-scheduler-engine" / "tasks.md"
TASK_REF = re.compile(r"\bT(\d{3})\b")


def _whitelist() -> dict[str, str]:
    """name -> reason. The reason is mandatory; see the tests below."""
    out: dict[str, str] = {}
    for raw in WHITELIST.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name, _, reason = line.partition("#")
        out[name.strip()] = reason.strip()
    return out


def _completed_tasks() -> set[str]:
    """Task ids marked [X] in tasks.md."""
    if not TASKS.exists():
        return set()
    return set(re.findall(r"^- \[[Xx]\] (T\d{3})\b", TASKS.read_text(), re.M))


def _sources() -> list[Path]:
    return [p for p in MODULE.rglob("*.py") if not p.name.startswith(".")]


def _defined() -> dict[str, Path]:
    """Public functions, methods and module-level constants."""
    found: dict[str, Path] = {}
    for path in _sources():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("_"):
                    continue
                # Abstract methods are contracts, not call sites.
                if any(getattr(d, "id", getattr(d, "attr", "")) == "abstractmethod" for d in node.decorator_list):
                    continue
                found.setdefault(node.name, path)
        # MODULE-LEVEL constants only — tree.body, not ast.walk. Both real
        # instances of this defect (KNOWN_INERT_TYPES, PINNED_LOCAL_SOURCES)
        # were module-level.
        #
        # Deliberately NOT enum members: walking into classes flags every value
        # in a vocabulary whose producer is not built yet — four of them on this
        # tree, all legitimately awaiting Phase 6. Each would need a whitelist
        # entry, and a whitelist that grows with every unbuilt feature is one
        # nobody reads, which is how this gate dies. Dead enum vocabulary is a
        # real if smaller problem; catching it is worth revisiting once the
        # engine is fully wired and the list would stay short.
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id.isupper() and not t.id.startswith("_"):
                        found.setdefault(t.id, path)
    return found


def _referenced() -> set[str]:
    """Every name mentioned anywhere in production code.

    A definition is NOT a reference to itself. That sounds obvious and was the
    bug the T055 sabotage found: an assignment target is an ast.Name, so a
    constant counted as referencing itself and every unused constant passed —
    which is the exact case (KNOWN_INERT_TYPES) that this check exists to catch.
    """
    names: set[str] = set()
    for path in _sources():
        tree = ast.parse(path.read_text(), filename=str(path))
        assigned_targets: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        assigned_targets.add(id(t))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                if id(node) in assigned_targets:
                    continue  # its own definition, not a use
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # A definition is not a reference to itself.
                continue
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for a in node.names:
                    names.add((a.asname or a.name).split(".")[0])
    return names


def test_module_exists() -> None:
    assert MODULE.is_dir() and _sources(), "this test would pass vacuously"


def test_nothing_is_defined_without_a_production_reference() -> None:
    """THE gate. The test tree is excluded: a test caller is not a caller."""
    defined, referenced, allowed = _defined(), _referenced(), _whitelist()
    orphans = {name: str(path.relative_to(MODULE)) for name, path in defined.items() if name not in referenced and name not in allowed}
    assert not orphans, f"defined but never referenced by production code — either wire it or whitelist it with a reason: {orphans}"


def test_every_whitelist_entry_carries_a_reason() -> None:
    """The obvious way this gate stops working is a silent whitelist.

    An entry without a reason is indistinguishable from one added to silence a
    real finding.
    """
    bare = [n for n, reason in _whitelist().items() if not reason]
    assert not bare, f"whitelist entries without a reason: {bare}"


def test_whitelist_has_no_stale_entries() -> None:
    """An entry for something that no longer exists is dead weight that makes
    the list harder to read, which is how the real entries stop being read."""
    defined = _defined()
    stale = [n for n in _whitelist() if n not in defined]
    assert not stale, f"whitelist names nothing that exists: {stale}"


def test_whitelist_entries_expire_when_their_task_completes() -> None:
    """The whitelist must SHRINK by construction, not merely be documented.

    Every entry names the task that will wire it. Once that task is marked
    complete, the entry has outlived its justification: either the wiring
    landed and the entry is now stale, or the task was closed without doing it
    — and the second case is exactly the wired-but-never-called defect this
    whole gate exists to catch, arriving through the back door.

    Without this, 43 entries of "caller lands later" quietly become permanent
    furniture, and the gate ends up exempting most of the module.
    """
    completed = _completed_tasks()
    expired: dict[str, str] = {}
    for name, reason in _whitelist().items():
        for task in TASK_REF.findall(reason):
            if f"T{task}" in completed:
                expired[name] = f"T{task} is complete"
    assert not expired, f"whitelist entries whose wiring task is already done — remove the entry if the caller landed, or reopen the task if it did not: {expired}"


def test_every_deferred_entry_names_a_task() -> None:
    """An entry deferred to 'later' with no task cannot expire, so it is
    permanent by omission. Only entries justified WITHOUT deferral may omit one.
    """
    missing = [name for name, reason in _whitelist().items() if any(w in reason.lower() for w in ("wired by", "lands", "later", "wires")) and not TASK_REF.search(reason)]
    assert not missing, f"deferred entries with no task id, so they can never expire: {missing}"


@pytest.mark.parametrize("blanket", ["*", "ALL", "everything"])
def test_whitelist_is_not_a_blanket(blanket) -> None:
    assert blanket not in _whitelist()
