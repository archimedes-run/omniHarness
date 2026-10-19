"""T083 — the read surfaces perform no writes (Feature 004 FR-030, SC-014; discharges FR-036).

Scans the read routers AND the view modules they delegate to, because a write
moved one call deeper is still a write. Three checks:

  1. every route is a GET;
  2. no call to a method that writes a store (the names this codebase's
     stores actually use);
  3. any rules `load()` passes notify=False — a notifying load runs the
     FR-042 supersede sweep, which resolves pending actions.

FR-036 (no rule editor) follows: an editor would have to write through one of
these modules.
"""

from __future__ import annotations

import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "app"

READ_SURFACES = [
    "gateway/routers/sessions.py",
    "gateway/routers/triggers.py",
    "gateway/routers/policy.py",
    "gateway/routers/tool_sources.py",
    "gateway/sessions_view.py",
    "gateway/triggers_view.py",
    "gateway/tool_sources.py",
    "policy/inspect.py",
]

#: Store-writing method names used in this codebase (JsonStore.set, PendingStore
#: save/resolve/claim, AuditLog.record, Scheduler.mark_fired, run stores put /
#: update_status, Path.write_text ...).
WRITE_METHODS = frozenset({"save", "set", "write_text", "write_bytes", "record", "record_tier3", "resolve", "claim", "mark_fired", "put", "update_status", "delete", "unlink", "rmdir", "rename", "expire_due", "forget", "defer", "hold"})
ROUTE_VERBS = frozenset({"post", "put", "patch", "delete"})
#: Only the POLICY ConfigLoader has listeners (the supersede sweep). The trigger
#: engine's ConfigLoader.load in triggers.py only parses, so check 3 is scoped
#: to the modules that read the policy loader — correctly narrow, not a one-off.
POLICY_LOADER_READERS = frozenset({"gateway/routers/policy.py", "policy/inspect.py"})


def _violations(rel: str) -> list[str]:
    tree = ast.parse((APP / rel).read_text())
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            name = node.func.attr
            if name in ROUTE_VERBS and isinstance(node.func.value, ast.Name) and node.func.value.id == "router":
                found.append(f"{rel}:{node.lineno} declares a {name.upper()} route")
            elif name in WRITE_METHODS:
                found.append(f"{rel}:{node.lineno} calls .{name}()")
            elif name == "load" and rel in POLICY_LOADER_READERS and not any(k.arg == "notify" and isinstance(k.value, ast.Constant) and k.value.value is False for k in node.keywords):
                found.append(f"{rel}:{node.lineno} calls .load() without notify=False (a notifying load supersedes pending actions)")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open":
            mode = node.args[1].value if len(node.args) > 1 and isinstance(node.args[1], ast.Constant) else "r"
            if any(c in str(mode) for c in "wax+"):
                found.append(f"{rel}:{node.lineno} opens a file for writing")
    return found


def test_the_gate_sees_a_write_when_there_is_one() -> None:
    """Positive control: the same scan, over a module known to write, finds it."""
    tree_src = "policy/pending.py"
    assert any(".resolve()" in v or ".save()" in v or "opens a file" in v for v in _violations(tree_src)), "the scan cannot see writes at all"


def test_read_surfaces_do_not_write() -> None:
    found = [v for rel in READ_SURFACES for v in _violations(rel)]
    assert not found, "a read surface writes:\n" + "\n".join(found)
