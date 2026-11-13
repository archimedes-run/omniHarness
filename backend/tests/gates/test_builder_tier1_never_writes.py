"""The builder's Tier 1 tools reach no write (Spec 010 FR-010, FR-026, Security table row 1).

`builder_draft`, `builder_read` and `builder_diff` run with no confirmation,
so nothing they reach may write the config store: a draft lives in the chat
(app/gateway/builder/drafts.py), never in the store. The card's precheck runs
before anyone has confirmed anything, so it is held to the same rule.

A static walk over app/gateway/builder/service.py: from each entry method,
every `self.<method>` it calls, transitively; none may call a store writer.
The writers are allowed only under `save`, `grant` and `undo`, which run
solely as a confirmed card's action (`_confirmed`).
"""

from __future__ import annotations

import ast
from pathlib import Path

SERVICE = Path(__file__).resolve().parents[2] / "app" / "gateway" / "builder" / "service.py"
ENTRY = ("draft", "read", "diff", "precheck")
WRITERS = frozenset({"write_agent", "write_skill", "write_automations", "write_rules", "edit_rules", "undo_rule", "undo", "record_installed", "mark_saved", "_save_skill", "_save_rule"})
CONFIRMED_ONLY = ("save", "grant", "undo")


def _methods() -> dict[str, ast.FunctionDef]:
    tree = ast.parse(SERVICE.read_text())
    [cls] = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "GatewayBuilderController"]
    return {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}


def _calls(node: ast.AST) -> tuple[set[str], set[str]]:
    """(self.<method> names called, every other called name)."""
    own, other = set(), set()
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        func = sub.func
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "self":
            own.add(func.attr)
        elif isinstance(func, ast.Attribute):
            other.add(func.attr)
        elif isinstance(func, ast.Name):
            other.add(func.id)
    return own, other


def reachable_writes(methods: dict[str, ast.FunctionDef], entry: str) -> set[str]:
    seen, todo, found = set(), [entry], set()
    while todo:
        name = todo.pop()
        if name in seen or name not in methods:
            continue
        seen.add(name)
        own, other = _calls(methods[name])
        found |= (own | other) & WRITERS
        todo += list(own)
    return found


def test_tier_one_builder_paths_reach_no_writer() -> None:
    methods = _methods()
    for entry in ENTRY:
        assert entry in methods, f"{entry} is not on the builder controller any more: update this gate"
        assert not reachable_writes(methods, entry), f"builder {entry} reaches a store write: {sorted(reachable_writes(methods, entry))}"


def test_every_write_path_starts_with_its_confirmation() -> None:
    methods = _methods()
    for name in CONFIRMED_ONLY:
        body = methods[name].body
        first = next(n for n in ast.walk(ast.Module(body=body, type_ignores=[])) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "_confirmed")
        assert first is not None
        # _confirmed is the first call the method makes.
        calls = [n for n in ast.walk(ast.Module(body=body, type_ignores=[])) if isinstance(n, ast.Call)]
        assert calls and calls[0] is first, f"builder {name} does something before checking its confirmation"


def test_the_gate_sees_a_write_when_there_is_one() -> None:
    """The gate is not vacuous: a draft that writes is caught."""
    source = "class GatewayBuilderController:\n    def draft(self):\n        self._helper()\n    def _helper(self):\n        config_versions.write_agent(1, 2, 3)\n"
    tree = ast.parse(source)
    methods = {n.name: n for n in tree.body[0].body if isinstance(n, ast.FunctionDef)}
    assert reachable_writes(methods, "draft") == {"write_agent"}
