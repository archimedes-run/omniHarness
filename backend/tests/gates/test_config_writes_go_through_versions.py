"""Every agent and skill config write goes through the one versioned store (Feature 006, user decision 2026-10-20).

`omniharness.config.config_versions` is where an agent's config.yaml and
SOUL.md and a custom skill's files are written, so that every change is a
version: who, when, what changed, its source, undoable, and refused when stale.
A second writer would make changes the history never saw.

Three scans over app/, packages/ and scripts/:

  1. no call to the skill storage's file writers (write_custom_skill,
     delete_custom_skill) outside the store;
  2. no module that names an agent's files (SOUL.md, SOUL_FILENAME) also
     writes files (write_text, yaml.dump, open for writing, replace), outside
     the store;
  3. (review round 2) no FUNCTION that reaches an agent's directory, and so
     its config.yaml (user_agent_dir, agent_dir, user_agents_dir, agents_dir,
     resolve_agent_dir, or an "agents" path joined with "config.yaml"), also
     writes, moves, copies or deletes files. config.yaml holds the agent's
     grants, so a second writer could grant without a version.
  4. (Spec 010 FR-022) no FUNCTION that reaches the trigger rules file
     (_resolve_rules_path, trigger_engine.rules_path, default_rules.json) also
     writes, moves or deletes files, outside app/gateway/automations_store.py;
     and inside it, the one function that writes files (_replace_file) is used
     only as the materialiser handed to config_versions.write_automations, so
     every write to the rules file is a recorded version.

ALLOWED names each exception and why. A stale entry fails.
"""

from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
ROOTS = (BACKEND / "app", BACKEND / "packages", BACKEND / "scripts")
STORE = "packages/harness/omniharness/config/config_versions.py"

SKILL_WRITERS = frozenset({"write_custom_skill", "delete_custom_skill"})
FILE_WRITES = frozenset({"write_text", "write_bytes", "dump", "replace", "rename"})
#: Ways to reach an agent's directory (omniharness.config.paths, agents_config).
AGENT_DIRS = frozenset({"user_agent_dir", "agent_dir", "user_agents_dir", "agents_dir", "resolve_agent_dir"})
#: Anything that changes files: scan 3 counts deleting and moving too.
TREE_WRITES = FILE_WRITES | frozenset({"safe_dump", "move", "copytree", "copy", "copy2", "copyfile", "rmtree", "unlink", "touch", "mkdir"})

RULES_STORE = "app/gateway/automations_store.py"
#: The rules file's writer inside the store, and the versioned call it may be
#: handed to (and nothing else).
RULES_WRITER = "_replace_file"
#: File-changing calls scan 4 counts (TREE_WRITES plus the low-level ones an
#: atomic write uses).
RULES_WRITES = TREE_WRITES | frozenset({"mkstemp", "fdopen", "NamedTemporaryFile", "fchmod"})

ALLOWED: dict[str, str] = {
    STORE: "the store itself",
    "scripts/migrate_user_isolation.py": "one-off migration run by hand with the gateway stopped: moves whole legacy agent directories into the per-user layout; the store records what it finds there as a baseline version on the next write",
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
    found += _agent_dir_writers(tree)
    return found


def _agent_dir_writers(tree: ast.AST) -> list[str]:
    """Scan 3, per function: reaches an agent's directory and changes files."""
    found = []
    scopes = [tree, *(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef))]
    for scope in scopes:
        body = scope.body if isinstance(scope, ast.Module) else [scope]
        nodes = [n for stmt in body for n in ast.walk(stmt)] if not isinstance(scope, ast.Module) else [n for stmt in body if not isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) for n in ast.walk(stmt)]
        constants = {n.value for n in nodes if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        reaches = any((isinstance(n, ast.Attribute) and n.attr in AGENT_DIRS) or (isinstance(n, ast.Name) and n.id in AGENT_DIRS) for n in nodes)
        reaches = reaches or ("config.yaml" in constants and ("agents" in constants or "lead_agent" in constants))
        if not reaches:
            continue
        writes = []
        for n in nodes:
            if isinstance(n, ast.Call):
                name = getattr(n.func, "attr", None) or getattr(n.func, "id", None)
                if name in TREE_WRITES or (name == "open" and len(n.args) > 1 and isinstance(n.args[1], ast.Constant) and any(c in str(n.args[1].value) for c in "wax+")):
                    writes.append(n.lineno)
        if writes:
            where = getattr(scope, "name", "module level")
            found.append(f"{where}() reaches an agent's directory (its config.yaml) and changes files (lines {sorted(set(writes))[:5]}) outside the versioned store")
    return found


def test_the_scan_sees_a_bypass() -> None:
    """Positive controls: each kind of bypass is seen."""
    assert violations("def f(s):\n    s.write_custom_skill('a', 'SKILL.md', 'x')\n")
    assert violations("def f(d):\n    (d / 'SOUL.md').write_text('x')\n")
    assert violations("from x import SOUL_FILENAME\ndef f(d):\n    open(d / SOUL_FILENAME, 'w')\n")
    assert not violations("def f(d):\n    return (d / 'SOUL.md').read_text()\n")
    # Scan 3: any writer of an agent's config.yaml, with or without SOUL.md.
    assert violations("def f(p, u, n):\n    (p.user_agent_dir(u, n) / 'config.yaml').write_text('autonomy: [tasks]')\n")
    assert violations("import shutil\ndef f(p, n):\n    shutil.rmtree(p.agent_dir(n))\n")
    assert violations("def f(home, u, n):\n    open(home / 'users' / u / 'agents' / n / 'config.yaml', 'w')\n")
    assert violations("import yaml\ndef f(root):\n    yaml.safe_dump({}, (root / 'lead_agent' / 'config.yaml').open('w'))\n")
    assert not violations("def f(p, u, n):\n    return (p.user_agent_dir(u, n) / 'config.yaml').read_text()\n")
    # Per function: a module that reads agent dirs in one function and writes
    # an unrelated file in another is not a writer of agent config.
    assert not violations("def r(p, u, n):\n    return p.user_agent_dir(u, n).exists()\ndef w(p):\n    p.user_md_file.write_text('x')\n")


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


# -- scan 4: the trigger rules file (Spec 010 FR-022) -------------------------


def _reaches_rules_file(nodes) -> bool:
    for n in nodes:
        if isinstance(n, ast.Name) and n.id == "_resolve_rules_path":
            return True
        if isinstance(n, ast.Attribute) and n.attr == "_resolve_rules_path":
            return True
        if isinstance(n, ast.alias) and n.name == "_resolve_rules_path":
            return True
        if isinstance(n, ast.Attribute) and n.attr == "rules_path" and isinstance(n.value, ast.Attribute) and n.value.attr == "trigger_engine":
            return True
        if isinstance(n, ast.Constant) and n.value == "default_rules.json":
            return True
    return False


def _writes(nodes) -> list[int]:
    out = []
    for n in nodes:
        if isinstance(n, ast.Call):
            name = getattr(n.func, "attr", None) or getattr(n.func, "id", None)
            if name in RULES_WRITES or (name == "open" and len(n.args) > 1 and isinstance(n.args[1], ast.Constant) and any(c in str(n.args[1].value) for c in "wax+")):
                out.append(n.lineno)
    return out


def rules_file_violations(source: str) -> list[str]:
    """Scan 4, per function (and module level): reaches the rules file and
    changes files."""
    tree = ast.parse(source)
    found = []
    functions = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)]
    module_nodes = [n for stmt in tree.body if not isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) for n in ast.walk(stmt)]
    for scope, nodes in [("module level", module_nodes), *((f.name, list(ast.walk(f))) for f in functions)]:
        if _reaches_rules_file(nodes):
            writes = _writes(nodes)
            if writes:
                found.append(f"{scope}() reaches the trigger rules file and changes files (lines {sorted(set(writes))[:5]}) outside the versioned store")
    return found


def rules_store_violations(source: str) -> list[str]:
    """Inside automations_store: only RULES_WRITER changes files, and it is
    referenced only inside the `materialise=` argument of a call to
    config_versions.write_automations."""
    tree = ast.parse(source)
    found = []
    for fn in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)):
        if fn.name != RULES_WRITER and _writes(list(ast.walk(fn))):
            found.append(f"{fn.name}() changes files; only {RULES_WRITER}() may, as the versioned store's materialiser")
    allowed_refs: set[int] = set()
    for call in (n for n in ast.walk(tree) if isinstance(n, ast.Call)):
        if (getattr(call.func, "attr", None) or getattr(call.func, "id", None)) == "write_automations":
            for kw in call.keywords:
                if kw.arg == "materialise":
                    allowed_refs |= {id(n) for n in ast.walk(kw.value)}
    for n in ast.walk(tree):
        if isinstance(n, ast.Name) and n.id == RULES_WRITER and id(n) not in allowed_refs:
            found.append(f"line {n.lineno}: {RULES_WRITER} used outside config_versions.write_automations(materialise=...)")
    if not allowed_refs:
        found.append("the rules file is never written through config_versions.write_automations")
    return found


def test_the_rules_file_scan_sees_a_bypass() -> None:
    """Positive controls for scan 4."""
    assert rules_file_violations("def f(cfg):\n    _resolve_rules_path(cfg).write_text('{}')\n")
    assert rules_file_violations("import os\ndef f(app):\n    p = app.trigger_engine.rules_path\n    os.replace('/tmp/x', p)\n")
    assert rules_file_violations("def f(cfg):\n    from app.gateway.trigger_engine_wiring import _resolve_rules_path\n    open(_resolve_rules_path(cfg), 'w')\n")
    assert not rules_file_violations("def f(cfg):\n    return _resolve_rules_path(cfg).read_text()\n")
    # Inside the store: a second writer, or the writer called directly.
    good = "def _replace_file(p, d):\n    p.write_text(d)\ndef write_rules(p, d):\n    write_automations(materialise=lambda: _replace_file(p, d))\n"
    assert not rules_store_violations(good)
    assert rules_store_violations(good + "def other(p):\n    p.write_text('x')\n")
    assert rules_store_violations(good + "def sneaky(p, d):\n    _replace_file(p, d)\n")


def test_the_rules_file_is_written_only_through_the_versioned_store() -> None:
    found = []
    for path in _files():
        rel = _rel(path)
        if rel == RULES_STORE:
            continue
        found += [f"{rel}: {v}" for v in rules_file_violations(path.read_text())]
    found += [f"{RULES_STORE}: {v}" for v in rules_store_violations((BACKEND / RULES_STORE).read_text())]
    assert not found, "a write to the trigger rules file bypasses the versioned store:\n" + "\n".join(found)
