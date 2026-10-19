"""The watcher's mcp dependency excludes 2.x (audit g).

mcp 2.x removed `Server.list_tools`, which server.py registers its tools with.
Verified in clean environments: 1.27.0 has it, 2.3.0 does not. With `mcp>=1.2.0`
unbounded, any install that resolved without the lockfile got a watcher that
cannot start.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from packaging.specifiers import SpecifierSet

PACKAGE = Path(__file__).resolve().parents[2] / "packages" / "session_watcher" / "pyproject.toml"


def _mcp_range() -> SpecifierSet:
    deps = tomllib.loads(PACKAGE.read_text())["project"]["dependencies"]
    [spec] = [d for d in deps if re.match(r"mcp\b", d)]
    return SpecifierSet(spec[len("mcp") :])


def test_the_locked_working_version_is_allowed() -> None:
    """Positive control: the range is read, and admits what works."""
    assert "1.27.0" in _mcp_range()


def test_mcp_2_is_excluded() -> None:
    assert "2.3.0" not in _mcp_range(), "mcp 2.x removed Server.list_tools; the watcher cannot start on it"
