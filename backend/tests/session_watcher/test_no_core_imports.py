"""T036 — core isolation (SC-008, Article I).

A runtime backstop for the static ruff ban. The lint rule catches the literal
`import omniharness`; this catches a transitive edge arriving through some other
module, which the linter cannot see.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[2] / "packages" / "session_watcher" / "session_watcher"
BANNED_ROOTS = {"omniharness", "langgraph", "langchain", "fastapi"}
BANNED_SHELL = {"subprocess"}


def _source_files() -> list[Path]:
    return [p for p in PKG.rglob("*.py")]


def test_package_directory_is_where_we_think_it_is() -> None:
    assert PKG.is_dir(), f"{PKG} not found; this test would pass vacuously"
    assert _source_files()


@pytest.mark.parametrize("path", _source_files(), ids=lambda p: p.name)
def test_no_banned_imports_statically(path: Path) -> None:
    tree = ast.parse(path.read_text(), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.append(node.module.split(".")[0])
    bad = (set(found) & BANNED_ROOTS) | (set(found) & BANNED_SHELL)
    assert not bad, f"{path.name} imports {sorted(bad)} — Article I / shell-out ban"


def test_importing_the_package_does_not_drag_in_core() -> None:
    """Transitive check the linter cannot do: import it and inspect sys.modules.

    Runs in a SUBPROCESS on purpose. An earlier version deleted omniharness,
    langgraph, langchain and fastapi from sys.modules in-process to get a clean
    slate — which is fine when this file runs alone and a landmine in the full
    suite, where 3,400 other tests depend on those modules being imported. It
    forces expensive re-imports and corrupts module-level singletons for every
    test that follows. A fresh interpreter gets the same clean slate and mutates
    nothing.
    """
    code = (
        "import sys, json\n"
        "import session_watcher.adapters.claude_code\n"
        "import session_watcher.discovery\n"
        "import session_watcher.redaction\n"
        "import session_watcher.registry\n"
        "import session_watcher.reply\n"
        "import session_watcher.state\n"
        "import session_watcher.summarize.mechanical\n"
        "print(json.dumps(sorted({m.split('.')[0] for m in sys.modules})))\n"
    )
    out = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert out.returncode == 0, f"importing the watcher failed:\n{out.stderr[-2000:]}"
    loaded = set(json.loads(out.stdout))
    leaked = loaded & BANNED_ROOTS
    assert not leaked, f"importing the watcher pulled in {sorted(leaked)} (Article I)"
