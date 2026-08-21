"""T085 — Article I backstop, in BOTH directions (SC-011, Gate 1).

The static ruff ban catches a literal `import langgraph.graph`. This catches a
transitive edge arriving through another module, which the linter cannot see —
and equally asserts that `langgraph_sdk` remains USABLE, because a gate that
only checks one direction lets a later "simplification" restore the glob.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[2] / "app" / "trigger_engine"
BANNED_ROOTS = {"omniharness", "langgraph"}
REQUIRED = {"langgraph_sdk"}


def _sources() -> list[Path]:
    return [p for p in MODULE.rglob("*.py") if not p.name.startswith(".")]


@pytest.mark.parametrize("path", _sources(), ids=lambda p: p.name)
def test_no_banned_imports_statically(path: Path) -> None:
    tree = ast.parse(path.read_text(), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.append(node.module.split(".")[0])
    bad = set(found) & BANNED_ROOTS
    assert not bad, f"{path.name} imports {sorted(bad)} — Article I"


def test_importing_the_engine_does_not_drag_in_core() -> None:
    """Transitive, in a subprocess so nothing shared is mutated."""
    code = "import sys, json\nimport app.trigger_engine.runner\nimport app.trigger_engine.loop\nimport app.trigger_engine.lifespan\nprint(json.dumps(sorted({m.split('.')[0] for m in sys.modules})))\n"
    out = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=180,
        cwd=str(MODULE.parents[1]),
    )
    assert out.returncode == 0, out.stderr[-2000:]
    loaded = set(json.loads(out.stdout))
    leaked = loaded & BANNED_ROOTS
    assert not leaked, f"importing the engine pulled in {sorted(leaked)} (Article I)"


def test_the_public_sdk_remains_importable() -> None:
    """The OTHER direction. `langgraph_sdk` is a client for a server, not a
    reach into internals, and banning it would break turn injection — which is
    a regression a one-directional test cannot see."""
    import importlib

    for name in REQUIRED:
        assert importlib.util.find_spec(name) is not None, f"{name} is required by FR-007"
