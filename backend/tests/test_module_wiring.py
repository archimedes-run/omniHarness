"""Repo-level wiring gate: every module under app/ must have a consumer.

Gate 4 (tests/trigger_engine/test_wiring.py) asks "is this name referenced by
other production code *inside the module*?" That scope is exactly where the
defect it was built for lives one level up: a module whose every internal name
is properly wired, but which nothing outside it ever imports, answers yes to
every question Gate 4 knows how to ask.

That is not hypothetical. `app/trigger_engine/` — Feature 002, 258 passing
tests — has no importer anywhere outside itself and its own tests. Gate 4 is
green on it. `lifespan.py`'s docstring even says it exists because "Gate 4
found that the loop was fully built and nothing started it"; the fix added the
starter and no caller, and Gate 4 cannot distinguish those two states.

A gate whose scope boundary sits exactly where the bug lives is the same shape
as the bug. This is the companion check.

Static imports only. A module reached by dotted-path string from config has no
static importer by design and belongs in the whitelist, where the reason is
mandatory and readable.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
APP = BACKEND / "app"
WHITELIST = APP / ".module-wiring-whitelist"

#: Trees that may import a module without counting as a consumer. A test
#: importing the thing it tests is not evidence that anything uses it — the
#: whole point of this gate.
NOT_A_CONSUMER = ("tests",)

#: Trees scanned for consumers.
SEARCH_ROOTS = ("app", "packages")


def _whitelist() -> dict[str, str]:
    """name -> reason. The reason is mandatory; see test_every_entry_has_a_reason."""
    out: dict[str, str] = {}
    for raw in WHITELIST.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name, _, reason = line.partition("#")
        out[name.strip()] = reason.strip()
    return out


def _modules() -> list[str]:
    """Top-level packages and modules directly under app/."""
    out = []
    for p in sorted(APP.iterdir()):
        if p.name.startswith((".", "_")):
            continue
        if p.is_dir() and (p / "__init__.py").exists():
            out.append(p.name)
        elif p.suffix == ".py":
            out.append(p.stem)
    return out


def _imported_modules(path: Path) -> set[str]:
    """Every `app.<x>` referenced by a static import in *path*."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError, OSError):
        return set()
    found: set[str] = set()
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative import — stays inside its own package
                continue
            if node.module:
                names = [node.module]
        for name in names:
            parts = name.split(".")
            if len(parts) >= 2 and parts[0] == "app":
                found.add(parts[1])
    return found


def consumers(module: str, *, root: Path | None = None) -> set[str]:
    """Files outside *module* and outside the test tree that import it."""
    root = root or BACKEND
    hits: set[str] = set()
    for tree_name in SEARCH_ROOTS:
        tree = root / tree_name
        if not tree.exists():
            continue
        for f in tree.rglob("*.py"):
            rel = f.relative_to(root)
            if rel.parts[0] in NOT_A_CONSUMER:
                continue
            if rel.parts[:2] == ("app", module):
                continue  # a module importing itself proves nothing
            if "tests" in rel.parts:
                continue
            if module in _imported_modules(f):
                hits.add(str(rel))
    return hits


def test_every_module_under_app_has_a_consumer():
    """The gate. An orphan module is code the running product cannot reach."""
    allowed = _whitelist()
    orphans = {m: consumers(m) for m in _modules()}
    unexplained = sorted(m for m, c in orphans.items() if not c and m not in allowed)

    assert not unexplained, (
        "these modules under app/ have no importer outside themselves and the "
        f"test tree, and are not whitelisted: {unexplained}. Either wire them "
        "into the running product or add an entry to "
        f"{WHITELIST.relative_to(BACKEND)} explaining why they have no static "
        "importer."
    )


def test_every_entry_has_a_reason():
    """An unexplained entry is indistinguishable from one added to silence a
    real finding."""
    missing = sorted(name for name, reason in _whitelist().items() if not reason)
    assert not missing, f"whitelist entries without a reason: {missing}"


def test_whitelist_has_no_stale_entries():
    """The list shrinks by construction.

    An entry naming a module that now HAS a consumer is debt that outlived its
    reason — most importantly `trigger_engine`, whose entry must be removed by
    the change that wires it.
    """
    stale = sorted(name for name in _whitelist() if consumers(name))
    assert not stale, f"these modules now have consumers and must be removed from the whitelist: {stale}"


def test_whitelist_names_real_modules():
    """A typo'd entry silently whitelists nothing and hides a real orphan."""
    known = set(_modules())
    unknown = sorted(name for name in _whitelist() if name not in known)
    assert not unknown, f"whitelist entries that are not modules under app/: {unknown}"


# ---------------------------------------------------------------------------
# Sabotage: the gate observed failing.
# ---------------------------------------------------------------------------


def test_gate_detects_an_orphan_module(tmp_path):
    """A gate never seen failing is indistinguishable from one that does nothing.

    Build a miniature app/ tree containing one wired module and one orphan, and
    confirm the checker separates them.
    """
    app = tmp_path / "app"
    (app / "wired").mkdir(parents=True)
    (app / "orphan").mkdir(parents=True)
    (app / "consumer").mkdir(parents=True)
    for pkg in ("wired", "orphan", "consumer"):
        (app / pkg / "__init__.py").write_text("")
    (app / "consumer" / "uses_it.py").write_text("from app.wired.thing import X\n")
    (app / "orphan" / "code.py").write_text("VALUE = 1\n")
    # a test-tree importer must NOT rescue the orphan
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_orphan.py").write_text("from app.orphan.code import VALUE\n")

    assert consumers("wired", root=tmp_path), "a genuinely imported module must pass"
    assert not consumers("orphan", root=tmp_path), "an orphan imported only by the test tree must still read as an orphan — that is the defect this gate exists for"


def test_self_import_does_not_count_as_a_consumer(tmp_path):
    """The failure mode that would make this gate useless: a module's own
    internal imports satisfying its own consumer check."""
    app = tmp_path / "app"
    (app / "solo").mkdir(parents=True)
    (app / "solo" / "__init__.py").write_text("")
    (app / "solo" / "a.py").write_text("from app.solo.b import thing\n")
    (app / "solo" / "b.py").write_text("thing = 1\n")

    assert not consumers("solo", root=tmp_path), "a module importing itself proves nothing about whether the product reaches it"


def test_trigger_engine_is_currently_an_orphan():
    """Pins the finding that motivated this gate, so the whitelist entry cannot
    quietly become permanent.

    When the gateway starts the engine this test fails, and its failure is the
    instruction: delete it and the whitelist entry together.
    """
    if consumers("trigger_engine"):
        pytest.fail("trigger_engine now has a consumer — remove its .module-wiring-whitelist entry and delete this test; the deferral it recorded is closed.")
