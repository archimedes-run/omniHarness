"""GATE A — no tool call reaches execution unclassified (FR-002, FR-003).

Every agent-construction site must reach the shared middleware base, which is
where the policy layer lives. Four of five already converge there. The fifth —
`agents/factory.py` — assembles its own chain via `_assemble_from_features`, has
no production consumer, and is exported as public API.

A GATE COVERING ONLY THE CONVERGENT FOUR WOULD HAVE ITS SCOPE BOUNDARY EXACTLY
WHERE THE BYPASS LIVES. That is the shape that let Feature 002 ship inert, and
the reason this gate enumerates call sites rather than trusting the ones it
knows.
"""

from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
SEARCH_ROOTS = ("app", "packages")

#: The function every agent-construction site must route through.
SHARED_BASE = "_build_runtime_middlewares"

#: Helpers that call the shared base. A site reaching one of these is compliant.
COMPLIANT_ASSEMBLERS = frozenset({SHARED_BASE, "build_lead_runtime_middlewares", "build_subagent_runtime_middlewares", "_build_middlewares"})

WHITELIST = BACKEND / "app" / "policy" / ".dispatch-whitelist"


def _whitelist() -> dict[str, str]:
    if not WHITELIST.exists():
        return {}
    out = {}
    for raw in WHITELIST.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name, _, reason = line.partition("#")
        out[name.strip()] = reason.strip()
    return out


def _call_sites() -> dict[str, list[int]]:
    """Every file calling create_agent, and the lines it does so on."""
    sites: dict[str, list[int]] = {}
    for root in SEARCH_ROOTS:
        for path in (BACKEND / root).rglob("*.py"):
            rel = path.relative_to(BACKEND)
            if "tests" in rel.parts:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError, OSError):
                continue
            lines = [node.lineno for node in ast.walk(tree) if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "create_agent"]
            if lines:
                sites[str(rel)] = lines
    return sites


def _reaches_shared_base(path: Path) -> bool:
    source = path.read_text(encoding="utf-8")
    return any(name in source for name in COMPLIANT_ASSEMBLERS)


def test_every_agent_construction_site_reaches_the_shared_middleware_base():
    """The gate."""
    allowed = _whitelist()
    offenders = []
    for rel, lines in _call_sites().items():
        if rel in allowed:
            continue
        if not _reaches_shared_base(BACKEND / rel):
            offenders.append(f"{rel}:{lines}")

    assert not offenders, (
        f"these agent-construction sites assemble their own middleware and so bypass the policy layer entirely: {sorted(offenders)}. Route them through {SHARED_BASE}, or whitelist with a reason in {WHITELIST.relative_to(BACKEND)}."
    )


def test_the_gate_actually_finds_call_sites():
    """A gate that enumerates nothing passes trivially.

    Article XII in miniature: the instrument must be seen detecting something.
    """
    sites = _call_sites()

    assert len(sites) >= 3, f"expected several create_agent sites, found {list(sites)} — the AST walk is not matching"


def test_every_whitelist_entry_has_a_reason():
    missing = sorted(name for name, reason in _whitelist().items() if not reason)

    assert not missing, f"whitelist entries without a reason: {missing}"


def test_whitelist_entries_name_real_files():
    unknown = sorted(name for name in _whitelist() if not (BACKEND / name).exists())

    assert not unknown, f"whitelist entries for files that do not exist: {unknown}"


def test_a_site_assembling_its_own_middleware_is_detected(tmp_path):
    """SABOTAGE, in a form that runs every time rather than by hand.

    Builds a file that calls create_agent with its own chain and confirms the
    detector flags it. If this stops failing, the gate has stopped looking.
    """
    bypass = tmp_path / "sneaky.py"
    bypass.write_text("from langchain.agents import create_agent\n\ndef build():\n    return create_agent(model=None, tools=[], middleware=[])\n")

    tree = ast.parse(bypass.read_text())
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "create_agent"]

    assert calls, "the detector did not find a create_agent call it was shown"
    assert not _reaches_shared_base(bypass), "the detector considered a self-assembling site compliant"
