"""Production imports are runtime dependencies (Article XIV, one layer out).

A package the gateway imports while serving requests must be installed by a
production install. `session-watcher` and `croniter` were dev-group only: the
suite always had them, so nothing failed, and a `--no-dev` image would have
shipped a gateway that redacts every channel message with a module it could
not import (audit W-1).

This used to check a hand list of those two, so it could only catch the case
that motivated it. The Feature 004 gate audit (T077) found the next one already
present: `cryptography`, imported at module top by app/gateway/mcp_secrets.py
and declared nowhere — installed only because unrelated packages happen to pull
it in. Now every third-party import under app/ is collected from the source and
must be declared by the backend, by a package the backend declares and we own
(the harness, the watcher), or listed below with a reason.
"""

from __future__ import annotations

import ast
import re
import sys
import tomllib
from importlib.metadata import packages_distributions
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
APP = BACKEND / "app"
#: Our own pyprojects: the backend, and the packages it declares as runtime
#: dependencies, whose own declared dependencies a production install brings.
PYPROJECTS = (BACKEND / "pyproject.toml", BACKEND / "packages/harness/pyproject.toml", BACKEND / "packages/session_watcher/pyproject.toml")
FIRST_PARTY = {"app", "omniharness", "session_watcher"}

#: Imported without being declared by us, and why that is safe.
NOT_DECLARED_ON_PURPOSE = {
    "starlette": "FastAPI is built on it and pins its range; importing its middleware base is importing FastAPI",
    "discord": "optional channel: app/channels/discord.py imports it inside try/except ImportError and logs that the channel is unavailable",
}
#: Declared, but by an extra rather than the default install: the import is lazy.
DECLARED_BY_EXTRA = {
    "psycopg": "the postgres extra (omniharness-harness[postgres]); app/trigger_engine/election.py imports it only for the Postgres lock",
}


def _normalise(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _requirement_name(req: str) -> str:
    return _normalise(re.split(r"[\s<>=!~;\[]", req, maxsplit=1)[0])


def _declared() -> set[str]:
    names: set[str] = set()
    for path in PYPROJECTS:
        names |= {_requirement_name(d) for d in tomllib.loads(path.read_text())["project"]["dependencies"]}
    return names


def _imported_top_levels(root: Path = APP) -> dict[str, str]:
    """Top-level module -> the first file importing it, for every absolute
    import under root, at any depth (a lazy import is still an import)."""
    found: dict[str, str] = {}
    for path in sorted(root.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                modules = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules = [node.module]
            else:
                continue
            for module in modules:
                top = module.split(".")[0]
                if top not in sys.stdlib_module_names and top not in FIRST_PARTY:
                    found.setdefault(top, str(path.relative_to(root)))
    return found


def _undeclared(imports: dict[str, str]) -> dict[str, str]:
    declared = _declared()
    distributions = packages_distributions()
    missing = {}
    for top, where in imports.items():
        dists = {_normalise(d) for d in distributions.get(top, [top])}
        if dists & declared or top in NOT_DECLARED_ON_PURPOSE or top in DECLARED_BY_EXTRA:
            continue
        missing[top] = f"{where} (distribution: {', '.join(sorted(dists))})"
    return missing


def test_the_parser_sees_a_known_runtime_dependency() -> None:
    """Positive control: fastapi is certainly declared and certainly imported."""
    assert "fastapi" in _declared()
    assert "fastapi" in _imported_top_levels()


def test_production_imports_are_runtime_dependencies() -> None:
    missing = _undeclared(_imported_top_levels())
    assert not missing, f"imported in production but not declared as a runtime dependency (dev-only, or only installed transitively): {missing}"


def test_every_exception_is_still_imported() -> None:
    """An exception for an import that went away is a stale licence."""
    stale = sorted((set(NOT_DECLARED_ON_PURPOSE) | set(DECLARED_BY_EXTRA)) - set(_imported_top_levels()))
    assert not stale, stale


def test_the_check_names_an_undeclared_import(tmp_path) -> None:
    """Sabotage, built in: a module importing a package only installed
    transitively is named; a declared one is not."""
    (tmp_path / "leaf.py").write_text("import anyio.abc\nimport fastapi\n")  # anyio: installed via httpx, declared by nobody
    assert set(_undeclared(_imported_top_levels(tmp_path))) == {"anyio"}
