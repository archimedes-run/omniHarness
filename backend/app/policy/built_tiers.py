"""Tiers of built MCP tools (Feature 006, #59).

A built server's tools never match the shared rules: their tier is the one
the user set on the approval screen, recorded with the approval in the
server's ``extensions_config.json`` entry (``built.tool_tiers``), and Tier 3
when unset. The file is re-read when its mtime changes, so every gateway
worker sees an approval as soon as it is written.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from omniharness.tools.names import canonical_tool_name

from .models import Tier

BUILT_PREFIX = "built__"

_lock = threading.Lock()
_cache: dict[str, object] = {"path": None, "mtime": None, "tiers": {}}


def _config_path() -> Path | None:
    from omniharness.config.extensions_config import ExtensionsConfig

    try:
        return ExtensionsConfig.resolve_config_path()
    except Exception:
        return None


def _load(path: Path) -> dict[str, dict[str, Tier]]:
    """{canonical server key: {canonical tool name: tier}} for built servers."""
    servers: dict[str, dict[str, Tier]] = {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return servers
    for key, entry in (data.get("mcpServers") or {}).items():
        if not canonical_tool_name(key).startswith(BUILT_PREFIX) or not isinstance(entry, dict):
            continue
        built = entry.get("built") or {}
        servers[canonical_tool_name(key)] = {canonical_tool_name(t): Tier(v) for t, v in (built.get("tool_tiers") or {}).items() if v in (1, 2, 3)}
    return servers


def is_built_tool(tool_name: str) -> bool:
    return canonical_tool_name(tool_name).startswith(BUILT_PREFIX)


def built_tool_tier(tool_name: str) -> Tier:
    """The tier set on the approval screen for this built tool; Tier 3 if none.

    The name must parse as exactly ONE built server's approved tool (#59
    review, #72): ``built__a_b_x`` could be built/a's tool ``b_x`` or
    built/a-b's tool ``x``; an ambiguous or unapproved name is Tier 3."""
    path = _config_path()
    servers: dict[str, dict[str, Tier]] = {}
    if path is not None:
        try:
            mtime = os.stat(path).st_mtime_ns
        except OSError:
            mtime = None
        with _lock:
            if _cache["path"] != str(path) or _cache["mtime"] != mtime:
                _cache.update(path=str(path), mtime=mtime, tiers=_load(path) if mtime is not None else {})
            servers = _cache["tiers"]  # type: ignore[assignment]
    name = canonical_tool_name(tool_name)
    parses = [(key, name[len(key) + 1 :]) for key in servers if name.startswith(key + "_")]
    if len(parses) != 1:
        return Tier.TIER_3
    key, tool = parses[0]
    return servers[key].get(tool, Tier.TIER_3)
