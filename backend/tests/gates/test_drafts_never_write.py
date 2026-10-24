"""The draft endpoint never writes (Feature 006 FR-301, T302).

A draft is shown for review; saving is the agents and skills APIs' job. So
the drafts router may call no store-writing method, write no file, and import
nothing that writes agents or skills. Scanned, like the read surfaces.
"""

from __future__ import annotations

import ast
from pathlib import Path

DRAFTS = Path(__file__).resolve().parents[2] / "app" / "gateway" / "routers" / "drafts.py"

WRITES = frozenset(
    {
        "save",
        "set",
        "write_text",
        "write_bytes",
        "write",
        "write_custom_skill",
        "append_history",
        "delete_custom_skill",
        "mkdir",
        "unlink",
        "rmtree",
        "rename",
        "replace",
        "dump",
        "record",
        "put",
        "update",
        "delete",
        "install_skill_from_archive",
        "ainstall_skill_from_archive",
    }
)
WRITING_MODULES = ("app.gateway.routers.agents", "app.gateway.routers.skills", "omniharness.tools.builtins.update_agent_tool", "omniharness.tools.builtins.setup_agent_tool", "shutil", "yaml")


def _violations(source: str) -> list[str]:
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if name in WRITES:
                found.append(f"line {node.lineno}: calls {name}()")
            if name == "open":
                mode = node.args[1].value if len(node.args) > 1 and isinstance(node.args[1], ast.Constant) else "r"
                if any(c in str(mode) for c in "wax+"):
                    found.append(f"line {node.lineno}: opens a file for writing")
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(WRITING_MODULES):
            found.append(f"line {node.lineno}: imports {node.module}")
        if isinstance(node, ast.Import) and any(a.name.startswith(WRITING_MODULES) for a in node.names):
            found.append(f"line {node.lineno}: imports a writing module")
    return found


def test_the_scan_sees_a_write() -> None:
    assert _violations("def f(s):\n    s.write_custom_skill('a', 'SKILL.md', 'x')\n"), "the scan cannot see writes"
    assert _violations("import shutil\n")


def test_the_drafts_router_never_writes() -> None:
    found = _violations(DRAFTS.read_text())
    assert not found, "the drafts router writes:\n" + "\n".join(found)
