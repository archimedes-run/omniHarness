"""T083 — the read surfaces perform no writes (Feature 004 FR-030, SC-014; discharges FR-036).

Scans the read routers AND the view modules they delegate to, because a write
moved one call deeper is still a write. Three checks:

  1. every route is a GET;
  2. no call to a method that writes a store (the names this codebase's
     stores actually use);
  3. any rules `load()` passes notify=False — a notifying load runs the
     FR-042 supersede sweep, which resolves pending actions.

FR-036 (no rule editor) held for Feature 004. Phase 2.5 adds ONE editor, and
the gate now names exactly which routers may write in these surfaces' API
namespaces (WRITE_ROUTERS, each with its reason). A router in those namespaces
that is neither a read surface nor named here fails, and only the automations
router may write the trigger rule file.

Scope (Feature 004 gate audit, T078): correctly narrow. FR-030 names these
surfaces. The list is enumerated, and a write two calls deep is not seen; both
are logged in ROADMAP-FOLLOWUPS.
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
    "gateway/routers/inbox.py",
    "gateway/inbox_view.py",
    "gateway/sessions_view.py",
    "gateway/triggers_view.py",
    "gateway/tool_sources.py",
    "policy/inspect.py",
]

#: The routers that MAY write in these namespaces, and why. Nothing else may.
WRITE_ROUTERS = {
    "gateway/routers/automations.py": "edits trigger rules through automations_store: validated by the engine's parser, written atomically, refused on a stale version",
    "gateway/routers/confirmations.py": "confirms or declines a pending Tier 3 action through confirm_flow, the single confirmation path",
}

#: The API namespaces of Feature 004's and Phase 2.5's surfaces.
NAMESPACES = ("/api/triggers", "/api/automations", "/api/policy", "/api/sessions", "/api/tool-sources", "/api/confirmations", "/api/inbox")

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


def _prefix(rel: str) -> str | None:
    tree = ast.parse((APP / rel).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "APIRouter":
            for k in node.keywords:
                if k.arg == "prefix" and isinstance(k.value, ast.Constant):
                    return k.value.value
    return None


def _routes(rel: str) -> list[str]:
    """Every path a router declares, prefix included."""
    prefix = _prefix(rel) or ""
    tree = ast.parse((APP / rel).read_text())
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == "router":
            if node.args and isinstance(node.args[0], ast.Constant):
                out.append(prefix + node.args[0].value)
    return out


def test_only_the_named_routers_write_in_these_namespaces() -> None:
    routers = sorted(str(p.relative_to(APP)) for p in (APP / "gateway" / "routers").glob("*.py"))
    in_scope = [r for r in routers if any(path.startswith(NAMESPACES) for path in _routes(r))]
    assert "gateway/routers/automations.py" in in_scope and "gateway/routers/triggers.py" in in_scope, "the namespace scan found nothing it should"
    unlisted = [r for r in in_scope if r not in READ_SURFACES and r not in WRITE_ROUTERS]
    assert not unlisted, f"a router serves a Feature 004 / 2.5 namespace but is neither a read surface nor a named writer: {unlisted}"
    assert all(reason for reason in WRITE_ROUTERS.values())


def test_only_the_automations_router_writes_the_rule_file() -> None:
    callers = []
    for path in APP.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", None)) == "write_rules":
                callers.append(str(path.relative_to(APP)))
    assert set(callers) == {"gateway/routers/automations.py"}, f"write_rules is called from {sorted(set(callers))}"
