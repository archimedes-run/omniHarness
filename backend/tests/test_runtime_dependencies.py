"""Production imports are runtime dependencies (Article XIV, one layer out).

A package the gateway imports while serving requests must be installed by a
production install. `session-watcher` and `croniter` were dev-group only: the
suite always had them, so nothing failed, and a `--no-dev` image would have
shipped a gateway that redacts every channel message with a module it could
not import (audit W-1).
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"

#: distribution -> a production module that imports it, so a reader knows why
#: each entry is here and can delete it when that import goes away.
IMPORTED_IN_PRODUCTION = {
    "session-watcher": "app/channels/base.py, app/gateway/trigger_engine_wiring.py (redaction)",
    "croniter": "app/trigger_engine/scheduler.py",
}


def _runtime_names() -> set[str]:
    deps = tomllib.loads(PYPROJECT.read_text())["project"]["dependencies"]
    return {re.split(r"[\s<>=!~;\[]", d, maxsplit=1)[0].lower() for d in deps}


def test_the_parser_sees_a_known_runtime_dependency() -> None:
    """Positive control: fastapi is certainly a runtime dependency."""
    assert "fastapi" in _runtime_names()


def test_production_imports_are_runtime_dependencies() -> None:
    missing = {name: why for name, why in IMPORTED_IN_PRODUCTION.items() if name not in _runtime_names()}
    assert not missing, f"imported in production but not a runtime dependency (dev-only?): {missing}"
