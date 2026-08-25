"""T023 — Gate: exactly ONE place takes the claim (FR-004).

The atomic claim is the only thing standing between two confirmation routes and
one action executing twice. A second implementation is not a style problem; it
is the defect. So the number of production call sites is asserted, not the
existence of a shared helper — a helper nobody is obliged to use protects
nothing.

Scoped to `app/`, not to `app/policy/`. A gate scoped to the module that
motivated it is how Gate 4 failed to see `recognise`, and the next route to
reimplement a claim will not be inside `app/policy/`.
"""

from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
SEARCH_ROOTS = ("app", "packages")
OWNER = "app/policy/confirm_flow.py"


def _call_sites() -> list[str]:
    """`.claim(...)` calls in production code, as file:line."""
    out = []
    for root in SEARCH_ROOTS:
        for path in sorted((BACKEND / root).rglob("*.py")):
            if "tests" in path.parts or path.name.startswith("."):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "claim":
                    out.append(f"{path.relative_to(BACKEND)}:{node.lineno}")
    return out


def test_the_detector_finds_the_call_it_is_shown(tmp_path):
    """POSITIVE CONTROL. A walk that matches nothing would pass this gate
    forever and report that as safety."""
    probe = tmp_path / "probe.py"
    probe.write_text("def f(store):\n    return store.claim('x', 'y')\n")
    tree = ast.parse(probe.read_text())
    found = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "claim"]
    assert found, "the detector did not find a claim call it was shown"


def test_exactly_one_production_call_site_takes_the_claim():
    sites = _call_sites()
    assert len(sites) == 1, f"expected one claim call site, found {sites}. A second confirmation route that takes its own claim allows one confirmation to execute twice."
    assert sites[0].startswith(OWNER), f"the claim is taken in {sites[0]}, not in {OWNER}"
