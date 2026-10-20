"""Every agent and skill config write goes through the one versioned store (Feature 006, user decision 2026-10-20).

`omniharness.config.config_versions` is where an agent's config.yaml and
SOUL.md and a custom skill's files are written, so that every change is a
version: who, when, what changed, its source, undoable, and refused when stale.
A second writer would make changes the history never saw.

Two scans over app/ and packages/:

  1. no call to the skill storage's file writers (write_custom_skill,
     delete_custom_skill) outside the store;
  2. no module that names an agent's files (SOUL.md, SOUL_FILENAME) also
     writes files (write_text, yaml.dump, open for writing, replace), outside
     the store.

ALLOWED names each exception and why. A stale entry fails.
"""

from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
ROOTS = (BACKEND / "app", BACKEND / "packages")
STORE = "packages/harness/omniharness/config/config_versions.py"

SKILL_WRITERS = frozenset({"write_custom_skill", "delete_custom_skill"})
FILE_WRITES = frozenset({"write_text", "write_bytes", "dump", "replace", "rename"})

ALLOWED: dict[str, str] = {
    STORE: "the store itself",
    # The storage classes define the writers the store calls.
    "packages/harness/omniharness/skills/storage/skill_storage.py": "defines the abstract writers the store calls",
    "packages/harness/omniharness/skills/storage/local_skill_storage.py": "implements the writers the store calls",
}


def _files():
    for root in ROOTS:
        for path in root.rglob("*.py"):
            if "/tests/" in str(path) or ".venv" in path.parts:
                continue
            yield path


def _rel(path: Path) -> str:
    return str(path.relative_to(BACKEND))


def violations(source: str) -> list[str]:
    tree = ast.parse(source)
    found: list[str] = []
    names_agent_files = False
    writes: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if name in SKILL_WRITERS:
                found.append(f"line {node.lineno}: calls {name}() outside the versioned store")
            if name in FILE_WRITES:
                writes.append(node.lineno)
            if name == "open" and len(node.args) > 1 and isinstance(node.args[1], ast.Constant) and any(c in str(node.args[1].value) for c in "wax+"):
                writes.append(node.lineno)
        if isinstance(node, ast.Constant) and node.value == "SOUL.md":
            names_agent_files = True
        if isinstance(node, ast.Name | ast.alias) and getattr(node, "id", getattr(node, "name", None)) == "SOUL_FILENAME":
            names_agent_files = True
    if names_agent_files and writes:
        found.append(f"names an agent's SOUL.md and writes files (lines {writes[:5]}) outside the versioned store")
    return found


def test_the_scan_sees_a_bypass() -> None:
    """Positive controls: each kind of bypass is seen."""
    assert violations("def f(s):\n    s.write_custom_skill('a', 'SKILL.md', 'x')\n")
    assert violations("def f(d):\n    (d / 'SOUL.md').write_text('x')\n")
    assert violations("from x import SOUL_FILENAME\ndef f(d):\n    open(d / SOUL_FILENAME, 'w')\n")
    assert not violations("def f(d):\n    return (d / 'SOUL.md').read_text()\n")


def test_agent_and_skill_config_is_written_only_by_the_versioned_store() -> None:
    found = []
    for path in _files():
        rel = _rel(path)
        if rel in ALLOWED:
            continue
        found += [f"{rel}: {v}" for v in violations(path.read_text())]
    assert not found, "an agent or skill config write bypasses the versioned store:\n" + "\n".join(found)


def test_allowed_entries_are_real_and_still_needed() -> None:
    for rel, reason in ALLOWED.items():
        assert reason, rel
        assert (BACKEND / rel).exists(), f"stale ALLOWED entry: {rel}"
